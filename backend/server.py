"""
FastAPI backend для AI Video Generator (DEMO-режим).

Реалізує конвеєр підготовки матеріалів:
тема -> сценарій -> сцени -> візуал -> озвучка -> субтитри -> файли.

Автоматичний монтаж (FFmpeg, editor.py) прибрано ПОВНІСТЮ - і з
основного пайплайна, і з тестової панелі - він був найважчим CPU-
навантаженням і найчастішою причиною примусових рестартів на слабкому
сервері. Сайт видає готові матеріали (картинки/відео сцен, аудіо
озвучки, .srt субтитри, script.json), а фінальний монтаж користувач
робить сам у будь-якому відеоредакторі.

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

from backend import ai, scene_generator, script_generator, subtitles, trends, voice_generator

# без цього logger.warning() у backend/*.py міг би тихо загубитись і не
# потрапити в консоль/логи хостингу (Python не пише логи нікуди, поки
# явно не налаштований хоча б один handler)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
VIDEOS_DIR = os.path.join(OUTPUT_DIR, "_scene_videos")
# НЕ під OUTPUT_DIR - той примонтований як публічна статика (/output/...),
# а тут лише службовий стан (internal fal.ai URL задач), не призначений
# для роздачі
STATE_DIR = os.path.join(BASE_DIR, "state")

ALLOWED_DURATIONS = (30, 60, 90)
STAGE_ORDER = ["script", "scenes", "visual", "voice", "subtitles", "export"]

# Максимальний вік файлу/задачі на диску і як часто перевіряти - без
# цього кожен клік "оживити сцену" накопичувався б на диску назавжди,
# поки контейнер живий.
FILE_MAX_AGE_SECONDS = 2 * 60 * 60  # 2 години
CLEANUP_INTERVAL_SECONDS = 30 * 60  # перевіряти раз на 30 хв


def _delete_old_video_files():
    """Видаляє відеофайли сцен, старші за FILE_MAX_AGE_SECONDS."""
    if not os.path.isdir(VIDEOS_DIR):
        return
    now = time.time()
    for filename in os.listdir(VIDEOS_DIR):
        path = os.path.join(VIDEOS_DIR, filename)
        try:
            if now - os.path.getmtime(path) > FILE_MAX_AGE_SECONDS:
                os.remove(path)
        except OSError:
            pass  # файл могли видалити паралельно - не критично


def _cleanup_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        _delete_old_video_files()
        _prune_video_jobs()
        _prune_jobs()


def _start_cleanup():
    _delete_old_video_files()
    _prune_video_jobs()
    _prune_jobs()
    thread = threading.Thread(target=_cleanup_loop, daemon=True)
    thread.start()


# --- Стійкий до рестарту стан video-задач оживлення сцен (fal.ai) ---
#
# video_jobs раніше жив ЛИШЕ в пам'яті процесу - будь-який рестарт
# сервера (деплой нового коду, примусовий рестарт Render через
# перевантаження CPU) стирав усі активні задачі, і клієнт бачив
# "Помилка при перевірці статусу", хоча сама генерація на fal.ai могла
# продовжуватись (і кошти вже списувались) незалежно від нашого сервера.
# Зберігаємо стан у JSON-файл після кожної зміни - при рестарті процес
# підхоплює задачі там, де зупинився.
VIDEO_JOBS_FILE = os.path.join(STATE_DIR, "video_jobs.json")


def _load_video_jobs() -> dict:
    try:
        with open(VIDEO_JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_video_jobs():
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(VIDEO_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(video_jobs, f)


def _prune_video_jobs():
    """Видаляє записи задач, старші за FILE_MAX_AGE_SECONDS - інакше
    файл (і словник у пам'яті) ріс би необмежено."""
    now = time.time()
    stale_ids = [
        job_id for job_id, job in video_jobs.items()
        if now - job.get("submitted_at", 0) > FILE_MAX_AGE_SECONDS
    ]
    for job_id in stale_ids:
        del video_jobs[job_id]
    if stale_ids:
        _save_video_jobs()

app = FastAPI(title="AI Video Generator (DEMO)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Стан задач основного генератора - зберігається на диск (той самий
# принцип, що й video_jobs), інакше рестарт процесу (примусовий
# рестарт Render через нестачу CPU/пам'яті - трапляється саме під час
# важкого етапу монтажу - або деплой нового коду) стирає задачу
# повністю, і користувач бачить голий 404/502 замість зрозумілої причини.
#
# Важливо: це НЕ дозволяє "доробити" перервану генерацію - run_pipeline
# виконується в одній Python-функції у фоновому потоці, і коли процес
# гине, вона гине разом з ним назавжди. Персистентність лише дає змогу
# показати чітке повідомлення про переривання замість плутаної помилки.
JOBS_FILE = os.path.join(STATE_DIR, "jobs.json")


def _load_jobs() -> dict:
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    # будь-яка задача, що лишилась "processing" з МИНУЛОГО запуску
    # процесу, гарантовано мертва - фоновий потік, що її виконував,
    # зник разом зі старим процесом
    for job in loaded.values():
        if job.get("status") == "processing":
            job["status"] = "error"
            job["error"] = "Генерацію перервано рестартом сервера. Спробуйте ще раз."
    return loaded


def _save_jobs():
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f)


jobs: dict = _load_jobs()


@app.on_event("startup")
def _start_trending_ideas_refresh():
    trends.start_background_refresh()


@app.on_event("startup")
def _start_output_cleanup():
    _start_cleanup()


class GenerateRequest(BaseModel):
    topic: str
    duration: int = 30
    language: str = "uk"


def _new_job_state(request: GenerateRequest) -> dict:
    return {
        "topic": request.topic,
        "duration": request.duration,
        "language": request.language,
        "status": "processing",
        "progress": 0,
        "current_stage": STAGE_ORDER[0],
        "stages": {stage: "pending" for stage in STAGE_ORDER},
        "error": None,
        "script": None,
        "result": None,
        "created_at": time.time(),
    }


def _prune_jobs():
    """Видаляє записи задач, старші за FILE_MAX_AGE_SECONDS - інакше
    файл (і словник у пам'яті) ріс би необмежено."""
    now = time.time()
    stale_ids = [
        job_id for job_id, job in jobs.items()
        if now - job.get("created_at", 0) > FILE_MAX_AGE_SECONDS
    ]
    for job_id in stale_ids:
        del jobs[job_id]
    if stale_ids:
        _save_jobs()


def _set_stage(job: dict, stage: str, status: str):
    job["stages"][stage] = status
    if status == "active":
        job["current_stage"] = stage
    done_count = sum(1 for s in job["stages"].values() if s == "done")
    job["progress"] = round(done_count / len(STAGE_ORDER) * 100, 3)
    _save_jobs()


def _make_stage_progress_callback(job: dict, stage: str):
    """Повертає функцію(fraction: 0..1), яка плавно рухає job["progress"]
    УСЕРЕДИНІ одного етапу (за номером етапу в STAGE_ORDER) - щоб під час
    довгих кроків (генерація картинок сцен) відсоток не "завис", а
    помітно рухався, навіть на дуже слабкому CPU безкоштовних хостингів."""
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
            scenes, scenes_dir,
            progress_callback=_make_stage_progress_callback(job, "visual"),
        )
        _set_stage(job, "visual", "done")

        _set_stage(job, "voice", "active")
        voice_files, silent_voice_count = voice_generator.generate_all_voices(scenes, audio_dir, job["language"])
        _set_stage(job, "voice", "done")

        _set_stage(job, "subtitles", "active")
        srt_path = os.path.join(job_dir, "subtitles.srt")
        subtitles.generate_srt(scenes, srt_path)
        _set_stage(job, "subtitles", "done")

        _set_stage(job, "export", "active")
        script_path = os.path.join(job_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        _set_stage(job, "export", "done")

        job["status"] = "done"
        job["progress"] = 100
        job["result"] = {
            "script_url": f"/output/{job_id}/script.json",
            "subtitles_url": f"/output/{job_id}/subtitles.srt",
            "scene_images": [f"/output/{job_id}/scenes/{os.path.basename(p)}" for p in scene_images],
            "voice_files": [f"/output/{job_id}/audio/{os.path.basename(p)}" for p in voice_files],
            "silent_voice_count": silent_voice_count,
        }
    except Exception as exc:  # локальний прототип: показуємо причину користувачу в UI
        job["status"] = "error"
        job["error"] = str(exc)
    _save_jobs()


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
    _save_jobs()

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


class RegenerateImageRequest(BaseModel):
    job_id: str
    scene_number: int
    visual_prompt: str


@app.post("/api/regenerate-image")
def regenerate_scene_image(request: RegenerateImageRequest):
    """Перегенерує картинку однієї сцени за (можливо відредагованим)
    промтом - щоб користувач міг виправити невдале зображення ДО того,
    як натисне платне «Оживити сцену» (image-to-video), яке саме з цієї
    картинки й починається."""
    job = jobs.get(request.job_id)
    if job is None or job["status"] != "done":
        raise HTTPException(404, "Задачу не знайдено або вона ще не завершена")

    scenes_dir = os.path.join(OUTPUT_DIR, request.job_id, "scenes")
    output_path = os.path.join(scenes_dir, f"scene_{request.scene_number:02d}.png")

    fake_scene = {"visual_prompt": request.visual_prompt, "scene": request.scene_number}
    scene_generator.generate_scene_image(fake_scene, output_path)

    # cache-bust - той самий шлях файлу, інакше браузер показав би стару
    # картинку з кешу замість щойно перегенерованої
    image_url = f"/output/{request.job_id}/scenes/{os.path.basename(output_path)}?v={int(time.time())}"
    return {"image_url": image_url}


# --- Оживлення окремої сцени рухом через fal.ai (image-to-video) -----
#
# Викликається вибірково, для однієї обраної сцени за раз (кнопка
# "Оживити сцену" в панелі результату на головній сторінці) - платно,
# лише за явним підтвердженням користувача, ніколи автоматично.

video_jobs: dict = _load_video_jobs()


class VideoRequest(BaseModel):
    visual_prompt: str
    image_data: str


@app.post("/api/video")
def generate_scene_video(request: VideoRequest):
    if not ai.has_video_api():
        raise HTTPException(400, "FAL_API_KEY не налаштований на сервері")

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # картинка приходить як base64 прямо від фронтенду (не шлях на диску) -
    # не залежить від того, чи вижив файл на сервері (Render безкоштовного
    # тарифу "засинає" при бездіяльності й перезапускає контейнер із
    # чистим ефемерним диском при пробудженні)
    header, _, encoded = request.image_data.partition(",")
    image_path = os.path.join(VIDEOS_DIR, f"{uuid.uuid4().hex[:10]}_source.png")
    with open(image_path, "wb") as f:
        f.write(base64.b64decode(encoded))

    # Лише миттєва постановка в чергу fal.ai (один швидкий HTTP-запит) -
    # саму генерацію (хвилини) опитує клієнт через GET нижче, без
    # довгого блокуючого циклу на сервері (див. docstring
    # ai.submit_video_job - таке блокування раніше підвищувало ризик
    # примусового рестарту процесу на слабкому CPU Render).
    job = ai.submit_video_job(image_path, request.visual_prompt)
    if job is None:
        raise HTTPException(502, "fal.ai не прийняв запит - деталі в логах сервера")

    job_id = uuid.uuid4().hex[:10]
    video_jobs[job_id] = {
        "status": "processing",
        "video_url": None,
        "error": None,
        "status_url": job["status_url"],
        "response_url": job["response_url"],
        "submitted_at": time.time(),
    }
    _save_video_jobs()
    return {"job_id": job_id}


@app.get("/api/video/{job_id}")
def get_scene_video_status(job_id: str):
    job = video_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Задачу не знайдено")

    if job["status"] == "processing":
        if time.time() - job["submitted_at"] > ai.FAL_MAX_WAIT_SECONDS:
            job["status"] = "error"
            job["error"] = f"не дочекались результату за {ai.FAL_MAX_WAIT_SECONDS} с"
            _save_video_jobs()
        else:
            output_path = os.path.join(VIDEOS_DIR, f"{job_id}.mp4")

            result = ai.check_video_job(job["status_url"], job["response_url"], output_path)
            if result == "done":
                job["status"] = "done"
                job["video_url"] = f"/output/_scene_videos/{job_id}.mp4"
                _save_video_jobs()
            elif result == "error":
                job["status"] = "error"
                job["error"] = "fal.ai не повернув результат - деталі причини дивіться в логах сервера"
                _save_video_jobs()

    return {"status": job["status"], "video_url": job["video_url"], "error": job["error"]}


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


os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
