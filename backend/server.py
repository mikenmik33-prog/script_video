"""
FastAPI backend для AI Video Generator (DEMO-режим).

Реалізує повний конвеєр:
тема -> сценарій -> сцени -> візуал -> озвучка -> субтитри -> монтаж -> MP4.

Запуск (з кореня проєкту):
    uvicorn backend.server:app --reload
Потім відкрити http://127.0.0.1:8000 у браузері.
"""

import base64
import json
import logging
import os
import threading
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import ai, editor, scene_generator, script_generator, subtitles, trends, voice_generator

# без цього logger.warning() у backend/*.py міг би тихо загубитись і не
# потрапити в консоль/логи хостингу (Python не пише логи нікуди, поки
# явно не налаштований хоча б один handler)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
MUSIC_DIR = os.path.join(ASSETS_DIR, "music")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEST_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "_test")

ALLOWED_DURATIONS = (30, 60, 90)
STAGE_ORDER = ["script", "scenes", "visual", "voice", "subtitles", "editing", "export"]

# Тестова панель (/test) не має власного очищення - без цього файли з
# кожного кліку "перегенерувати" накопичувались би на диску назавжди,
# поки контейнер живий. Максимальний вік файлу і як часто перевіряти.
TEST_FILE_MAX_AGE_SECONDS = 2 * 60 * 60  # 2 години
TEST_CLEANUP_INTERVAL_SECONDS = 30 * 60  # перевіряти раз на 30 хв


def _delete_old_test_files():
    """Видаляє тестові файли, старші за TEST_FILE_MAX_AGE_SECONDS."""
    if not os.path.isdir(TEST_OUTPUT_DIR):
        return
    now = time.time()
    for root, _dirs, filenames in os.walk(TEST_OUTPUT_DIR):
        for filename in filenames:
            path = os.path.join(root, filename)
            try:
                if now - os.path.getmtime(path) > TEST_FILE_MAX_AGE_SECONDS:
                    os.remove(path)
            except OSError:
                pass  # файл могли видалити паралельно - не критично


def _test_cleanup_loop():
    while True:
        time.sleep(TEST_CLEANUP_INTERVAL_SECONDS)
        _delete_old_test_files()


def _start_test_cleanup():
    # На старті видаляємо лише СТАРІ файли (з минулих сесій, давніші за
    # TEST_FILE_MAX_AGE_SECONDS) - не всю папку одразу. Раніше тут був
    # повний shutil.rmtree() при кожному запуску, через що деплой чи
    # рестарт Render видаляв щойно згенеровані картинки посеред роботи
    # користувача на /test.
    _delete_old_test_files()
    thread = threading.Thread(target=_test_cleanup_loop, daemon=True)
    thread.start()

app = FastAPI(title="AI Video Generator (DEMO)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Проста in-memory "база" задач. Без бази даних - достатньо для локального
# прототипу; стан живе, поки працює процес сервера.
jobs: dict = {}


@app.on_event("startup")
def _start_trending_ideas_refresh():
    trends.start_background_refresh()


@app.on_event("startup")
def _start_test_output_cleanup():
    _start_test_cleanup()


class GenerateRequest(BaseModel):
    topic: str
    duration: int = 30
    style: str = "cinematic"
    language: str = "uk"


def _new_job_state(request: GenerateRequest) -> dict:
    return {
        "topic": request.topic,
        "duration": request.duration,
        "style": request.style,
        "language": request.language,
        "status": "processing",
        "progress": 0,
        "current_stage": STAGE_ORDER[0],
        "stages": {stage: "pending" for stage in STAGE_ORDER},
        "error": None,
        "script": None,
        "result": None,
    }


def _set_stage(job: dict, stage: str, status: str):
    job["stages"][stage] = status
    if status == "active":
        job["current_stage"] = stage
    done_count = sum(1 for s in job["stages"].values() if s == "done")
    job["progress"] = round(done_count / len(STAGE_ORDER) * 100, 3)


def _make_stage_progress_callback(job: dict, stage: str):
    """Повертає функцію(fraction: 0..1), яка плавно рухає job["progress"]
    УСЕРЕДИНІ одного етапу (за номером етапу в STAGE_ORDER) - щоб під час
    довгих кроків (найдовший - монтаж) відсоток не "завис", а помітно
    рухався, навіть на дуже слабкому CPU безкоштовних хостингів."""
    stage_index = STAGE_ORDER.index(stage)
    stage_span = 100 / len(STAGE_ORDER)
    base_progress = stage_index * stage_span

    def callback(fraction: float):
        job["progress"] = round(base_progress + fraction * stage_span, 3)

    return callback


def run_pipeline(job_id: str):
    """Виконує весь конвеєр генерації відео для однієї задачі.

    FastAPI/Starlette запускає звичайні (не async) фонові задачі в
    окремому потоці, тому цей блокуючий код (FFmpeg тощо) не заважає
    іншим запитам (наприклад, опитуванню статусу).
    """
    job = jobs[job_id]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    scenes_dir = os.path.join(job_dir, "scenes")
    audio_dir = os.path.join(job_dir, "audio")
    work_dir = os.path.join(job_dir, "work")

    try:
        _set_stage(job, "script", "active")
        script = script_generator.generate_script(job["topic"], job["duration"], job["language"])
        job["script"] = script
        _set_stage(job, "script", "done")

        _set_stage(job, "scenes", "active")
        scenes = script["scenes"]
        _set_stage(job, "scenes", "done")

        _set_stage(job, "visual", "active")
        scene_images = scene_generator.generate_all_scenes(
            scenes, job["style"], scenes_dir,
            progress_callback=_make_stage_progress_callback(job, "visual"),
        )
        _set_stage(job, "visual", "done")

        _set_stage(job, "voice", "active")
        voice_files = voice_generator.generate_all_voices(scenes, audio_dir, job["language"])
        _set_stage(job, "voice", "done")

        _set_stage(job, "subtitles", "active")
        srt_path = os.path.join(job_dir, "subtitles.srt")
        subtitles.generate_srt(scenes, srt_path)
        _set_stage(job, "subtitles", "done")

        _set_stage(job, "editing", "active")
        final_video_path = os.path.join(job_dir, "final.mp4")
        editor.build_video(
            scenes=scenes,
            scene_images=scene_images,
            voice_files=voice_files,
            work_dir=work_dir,
            music_dir=MUSIC_DIR,
            output_path=final_video_path,
            progress_callback=_make_stage_progress_callback(job, "editing"),
        )
        _set_stage(job, "editing", "done")

        _set_stage(job, "export", "active")
        script_path = os.path.join(job_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        _set_stage(job, "export", "done")

        job["status"] = "done"
        job["progress"] = 100
        job["result"] = {
            "video_url": f"/output/{job_id}/final.mp4",
            "script_url": f"/output/{job_id}/script.json",
            "subtitles_url": f"/output/{job_id}/subtitles.srt",
            "scene_images": [f"/output/{job_id}/scenes/{os.path.basename(p)}" for p in scene_images],
            "voice_files": [f"/output/{job_id}/audio/{os.path.basename(p)}" for p in voice_files],
        }
    except Exception as exc:  # локальний прототип: показуємо причину користувачу в UI
        job["status"] = "error"
        job["error"] = str(exc)


@app.get("/api/trending-ideas")
def get_trending_ideas():
    """Список ідей теми з найпопулярніших відео YouTube (від найбільш до
    найменш популярного за переглядами). Оновлюється у фоні автоматично."""
    return trends.get_ideas()


@app.post("/api/trending-ideas/refresh")
def refresh_trending_ideas():
    """Примусово оновлює список ідей зараз, не чекаючи фонового розкладу."""
    updated = trends.refresh_ideas()
    return {"updated": updated, **trends.get_ideas()}


@app.post("/api/generate")
def generate_video(request: GenerateRequest, background_tasks: BackgroundTasks):
    if not request.topic or not request.topic.strip():
        raise HTTPException(400, "Тема відео не може бути порожньою")
    if request.duration not in ALLOWED_DURATIONS:
        raise HTTPException(400, "Непідтримувана тривалість відео")

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = _new_job_state(request)

    background_tasks.add_task(run_pipeline, job_id)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def get_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задачу не знайдено")
    return {
        "status": job["status"],
        "progress": job["progress"],
        "current_stage": job["current_stage"],
        "stages": job["stages"],
        "error": job["error"],
    }


@app.get("/api/result/{job_id}")
def get_result(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задачу не знайдено")
    if job["status"] != "done":
        raise HTTPException(409, "Відео ще не готове")
    return {
        "topic": job["topic"],
        "script": job["script"],
        "result": job["result"],
    }


# --- Тестова панель: швидка ітерація коротких сценаріїв (до 15с) і
# візуальних промтів, без повного циклу генерації відео/монтажу. ---

TEST_MAX_DURATION = 15

# Окрема in-memory "база" для тестових video-задач (fal.ai) - та сама
# логіка, що й jobs, але навмисно окремий словник, щоб тестова панель
# не змішувалась зі станом основного генератора відео.
test_video_jobs: dict = {}


class TestScriptRequest(BaseModel):
    topic: str
    duration: int = TEST_MAX_DURATION
    language: str = "uk"


@app.post("/api/test/script")
def test_generate_script(request: TestScriptRequest):
    if not request.topic or not request.topic.strip():
        raise HTTPException(400, "Тема не може бути порожньою")
    duration = max(5, min(request.duration, TEST_MAX_DURATION))
    script = script_generator.generate_script(request.topic, duration, request.language)
    return {"script": script}


class TestImageRequest(BaseModel):
    visual_prompt: str
    style: str = "cinematic"


@app.post("/api/test/image")
def test_generate_image(request: TestImageRequest):
    if not request.visual_prompt.strip():
        raise HTTPException(400, "Промт не може бути порожнім")

    images_dir = os.path.join(TEST_OUTPUT_DIR, "images")
    os.makedirs(images_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:10]}.png"
    path = os.path.join(images_dir, filename)

    # generate_scene_image() очікує "сцену" - для тестової панелі досить
    # мінімального словника з тим самим промтом, який редагує користувач
    fake_scene = {"scene": 0, "visual_prompt": request.visual_prompt}
    scene_generator.generate_scene_image(fake_scene, request.style, path)

    # base64 повертаємо одразу у відповіді, щоб фронтенд зберіг байти
    # картинки в себе в пам'яті - Render безкоштовного тарифу "засинає"
    # при бездіяльності й при пробудженні перезапускає контейнер із
    # чистим ефемерним диском, тому файл за посиланням image_url може
    # зникнути ще до того, як користувач натисне "Згенерувати відео"
    with open(path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    return {
        "image_url": f"/output/_test/images/{filename}",
        "image_data": f"data:image/png;base64,{image_b64}",
    }


class TestVideoRequest(BaseModel):
    visual_prompt: str
    image_url: str | None = None
    image_data: str | None = None


@app.post("/api/test/video")
def test_generate_video(request: TestVideoRequest):
    if not ai.has_video_api():
        raise HTTPException(400, "FAL_API_KEY не налаштований на сервері")

    images_dir = os.path.join(TEST_OUTPUT_DIR, "images")
    os.makedirs(images_dir, exist_ok=True)

    if request.image_data:
        # надійний шлях - байти картинки прийшли прямо від фронтенду,
        # не залежить від того, чи вижив файл на диску сервера
        header, _, encoded = request.image_data.partition(",")
        image_path = os.path.join(images_dir, f"{uuid.uuid4().hex[:10]}.png")
        with open(image_path, "wb") as f:
            f.write(base64.b64decode(encoded))
    elif request.image_url:
        relative_path = request.image_url.removeprefix("/output/")
        image_path = os.path.join(OUTPUT_DIR, relative_path)
        if not os.path.exists(image_path):
            raise HTTPException(404, "Зображення для цієї сцени не знайдено")
    else:
        raise HTTPException(400, "Не передано зображення сцени")

    # Лише миттєва постановка в чергу fal.ai (один швидкий HTTP-запит) -
    # саму генерацію (хвилини) опитує клієнт через GET нижче, без
    # довгого блокуючого циклу на сервері (див. docstring
    # ai.submit_video_job - таке блокування раніше підвищувало ризик
    # примусового рестарту процесу на слабкому CPU Render).
    job = ai.submit_video_job(image_path, request.visual_prompt)
    if job is None:
        raise HTTPException(502, "fal.ai не прийняв запит - деталі в логах сервера")

    job_id = uuid.uuid4().hex[:10]
    test_video_jobs[job_id] = {
        "status": "processing",
        "video_url": None,
        "error": None,
        "status_url": job["status_url"],
        "response_url": job["response_url"],
        "submitted_at": time.time(),
    }
    return {"job_id": job_id}


@app.get("/api/test/video/{job_id}")
def get_test_video_status(job_id: str):
    job = test_video_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задачу не знайдено")

    if job["status"] == "processing":
        if time.time() - job["submitted_at"] > ai.FAL_MAX_WAIT_SECONDS:
            job["status"] = "error"
            job["error"] = f"не дочекались результату за {ai.FAL_MAX_WAIT_SECONDS} с"
        else:
            videos_dir = os.path.join(TEST_OUTPUT_DIR, "videos")
            os.makedirs(videos_dir, exist_ok=True)
            output_path = os.path.join(videos_dir, f"{job_id}.mp4")

            result = ai.check_video_job(job["status_url"], job["response_url"], output_path)
            if result == "done":
                job["status"] = "done"
                job["video_url"] = f"/output/_test/videos/{job_id}.mp4"
            elif result == "error":
                job["status"] = "error"
                job["error"] = "fal.ai не повернув результат - деталі причини дивіться в логах сервера"

    return {"status": job["status"], "video_url": job["video_url"], "error": job["error"]}


@app.get("/health")
def health_check():
    # Легкий ендпоінт спеціально для зовнішнього пінгера (UptimeRobot
    # тощо), щоб не давати Render безкоштовного тарифу засинати після
    # ~15 хв бездіяльності - нічого не читає з диску й не викликає
    # жодного AI-сервісу, тому пінг кожні кілька хвилин нічого не коштує.
    return {"status": "ok"}


# --- Роздача frontend-файлів (лежать у корені проєкту, не в backend/) ---


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/style.css")
def serve_css():
    return FileResponse(os.path.join(BASE_DIR, "style.css"))


@app.get("/script.js")
def serve_js():
    return FileResponse(os.path.join(BASE_DIR, "script.js"))


@app.get("/test")
def serve_test_page():
    return FileResponse(os.path.join(BASE_DIR, "test.html"))


@app.get("/test.js")
def serve_test_js():
    return FileResponse(os.path.join(BASE_DIR, "test.js"))


os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
