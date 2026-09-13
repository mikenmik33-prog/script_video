"""
FastAPI backend для AI Video Generator (DEMO-режим).

Реалізує повний конвеєр:
тема -> сценарій -> сцени -> візуал -> озвучка -> субтитри -> монтаж -> MP4.

Запуск (з кореня проєкту):
    uvicorn backend.server:app --reload
Потім відкрити http://127.0.0.1:8000 у браузері.
"""

import json
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import editor, scene_generator, script_generator, subtitles, voice_generator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
MUSIC_DIR = os.path.join(ASSETS_DIR, "music")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

ALLOWED_DURATIONS = (30, 60, 90)
STAGE_ORDER = ["script", "scenes", "visual", "voice", "subtitles", "editing", "export"]

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
        scene_images = scene_generator.generate_all_scenes(scenes, job["style"], scenes_dir)
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
