"""
FastAPI backend для AI Video Generator (DEMO-режим).

Реалізує конвеєр підготовки матеріалів у 2 етапи з ручним
затвердженням користувача:
тема -> сценарій+озвучка -> [затверджую] -> субтитри+файли.

Застосунок НЕ генерує ні картинки, ні відео - лише текст (сценарій,
детальний промт кожної сцени, рекомендований промт руху камери) й
озвучку. Користувач сам вставляє детальний промт сцени в Google Flow
(чи інший text-to-video інструмент) і отримує готове відео напряму,
без проміжного фото - за рішенням користувача (генерація картинок
через fal.ai виявилась зайвим кроком).

Автоматичний монтаж (FFmpeg, editor.py) прибрано ПОВНІСТЮ - і з
основного пайплайна, і з тестової панелі - він був найважчим CPU-
навантаженням і найчастішою причиною примусових рестартів на слабкому
сервері.

Запуск (з кореня проєкту):
    uvicorn backend.server:app --reload
Потім відкрити http://127.0.0.1:8000 у браузері.
"""

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

from backend import script_generator, subtitles, trends, voice_generator

# без цього logger.warning() у backend/*.py міг би тихо загубитись і не
# потрапити в консоль/логи хостингу (Python не пише логи нікуди, поки
# явно не налаштований хоча б один handler)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
# НЕ під OUTPUT_DIR - той примонтований як публічна статика (/output/...),
# а тут лише службовий стан задач, не призначений для роздачі
STATE_DIR = os.path.join(BASE_DIR, "state")

# Пайплайн розбитий на 2 етапи з ручним затвердженням користувачем між
# ними (script -> ЗАТВЕРДЖУЮ -> export), а не один суцільний прогін -
# користувач хоче бачити й правити текст сцен ДО фінального експорту.
# Озвучка в тому ж етапі, що й сценарій - так користувач одразу бачить
# реальну тривалість кожної репліки.
STAGE_ORDER = ["script", "voice", "export"]

# Максимальний вік задачі на диску і як часто перевіряти - без цього
# jobs.json ріс би необмежено, поки контейнер живий.
FILE_MAX_AGE_SECONDS = 2 * 60 * 60  # 2 години
CLEANUP_INTERVAL_SECONDS = 30 * 60  # перевіряти раз на 30 хв


def _cleanup_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        _prune_jobs()


def _start_cleanup():
    _prune_jobs()
    thread = threading.Thread(target=_cleanup_loop, daemon=True)
    thread.start()


app = FastAPI(title="AI Video Generator (DEMO)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Стан задач основного генератора - зберігається на диск, інакше
# рестарт процесу (примусовий рестарт Render через нестачу CPU/пам'яті
# або деплой нового коду) стирає задачу повністю, і користувач бачить
# голий 404/502 замість зрозумілої причини.
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
    language: str = "uk"


def _new_job_state(request: GenerateRequest) -> dict:
    return {
        "topic": request.topic,
        "language": request.language,
        # "processing" -> "script_review" (користувач редагує/затверджує
        # текст сцен) -> "processing" -> "done"/"error"
        "status": "processing",
        "progress": 0,
        "current_stage": STAGE_ORDER[0],
        "stages": {stage: "pending" for stage in STAGE_ORDER},
        "error": None,
        "script": None,
        "voice_files": None,
        "silent_voice_count": 0,
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


def _job_dirs(job_id: str) -> tuple:
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    return job_dir, os.path.join(job_dir, "audio")


def run_script_stage(job_id: str):
    """Етап 1: сценарій + озвучка (щоб одразу бачити реальну тривалість
    реплік). Завершується статусом "script_review" - конвеєр ЗУПИНЯЄТЬСЯ
    і чекає, поки користувач перегляне/відредагує текст сцен і натисне
    "Затвердити сценарій" (POST /api/script/{job_id}/approve)."""
    job = jobs[job_id]
    _, audio_dir = _job_dirs(job_id)

    try:
        _set_stage(job, "script", "active")
        script = script_generator.generate_script(job["topic"], job["language"])
        job["script"] = script
        _set_stage(job, "script", "done")

        _set_stage(job, "voice", "active")
        voice_files, silent_voice_count = voice_generator.generate_all_voices(
            script["scenes"], audio_dir, job["language"],
        )
        job["voice_files"] = [f"/output/{job_id}/audio/{os.path.basename(p)}" for p in voice_files]
        job["silent_voice_count"] = silent_voice_count
        _set_stage(job, "voice", "done")

        job["status"] = "script_review"
    except Exception as exc:  # локальний прототип: показуємо причину користувачу в UI
        job["status"] = "error"
        job["error"] = str(exc)
    _save_jobs()


def run_finalize_stage(job_id: str):
    """Етап 2: субтитри + експорт файлів (після затвердження сценарію).
    Завершується статусом "done" - фінальний результат готовий."""
    job = jobs[job_id]
    job_dir, _ = _job_dirs(job_id)
    script = job["script"]

    try:
        _set_stage(job, "export", "active")
        srt_path = os.path.join(job_dir, "subtitles.srt")
        subtitles.generate_srt(script["scenes"], srt_path)

        script_path = os.path.join(job_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        _set_stage(job, "export", "done")

        job["status"] = "done"
        job["progress"] = 100
        job["result"] = {
            "script_url": f"/output/{job_id}/script.json",
            "subtitles_url": f"/output/{job_id}/subtitles.srt",
            "voice_files": job["voice_files"],
            "silent_voice_count": job["silent_voice_count"],
        }
    except Exception as exc:
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

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = _new_job_state(request)
    _save_jobs()

    background_tasks.add_task(run_script_stage, job_id)
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


# --- Етап 1: перегляд/редагування сценарію ДО генерації картинок -----


@app.get("/api/script/{job_id}")
def get_script_for_review(job_id: str):
    job = jobs.get(job_id)
    if job is None or job["script"] is None:
        raise HTTPException(404, "Сценарій ще не готовий")
    return {
        "topic": job["topic"],
        "script": job["script"],
        "voice_files": job["voice_files"],
        "silent_voice_count": job["silent_voice_count"],
    }


class SceneEdit(BaseModel):
    scene: int
    voice_text: str
    visual_prompt: str


class ApproveScriptRequest(BaseModel):
    scenes: list[SceneEdit]


@app.post("/api/script/{job_id}/approve")
def approve_script(job_id: str, request: ApproveScriptRequest, background_tasks: BackgroundTasks):
    job = jobs.get(job_id)
    if job is None or job["status"] != "script_review":
        raise HTTPException(409, "Сценарій зараз не на розгляді")

    scenes_by_number = {s["scene"]: s for s in job["script"]["scenes"]}
    _, audio_dir = _job_dirs(job_id)

    for edit in request.scenes:
        scene = scenes_by_number.get(edit.scene)
        if scene is None:
            continue
        scene["visual_prompt"] = edit.visual_prompt.strip()
        new_voice_text = edit.voice_text.strip()
        if new_voice_text != scene["voice_text"]:
            # текст цієї репліки відредаговано вручну - перегенеровуємо
            # ЛИШЕ її аудіо (і subtitle - при ручному редагуванні втрачаємо
            # розрізнення "цифри словами/цифрами", subtitle стає тим самим
            # текстом), решту сцен не чіпаємо, щоб не витрачати час/квоту
            # edge-tts даремно
            scene["voice_text"] = new_voice_text
            scene["subtitle"] = new_voice_text
            voice_path = os.path.join(audio_dir, f"voice_{scene['scene']:02d}.mp3")
            voice_generator.generate_voice_for_scene(scene, voice_path, job["language"])

    job["script"]["full_text"] = " ".join(s["voice_text"] for s in job["script"]["scenes"])
    job["status"] = "processing"
    _save_jobs()

    background_tasks.add_task(run_finalize_stage, job_id)
    return {"ok": True}


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
