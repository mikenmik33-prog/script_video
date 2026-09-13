"""
DEMO-генератор озвучки.

Пізніше сюди можна підключити реальний TTS API - достатньо реалізувати
ai.generate_voice_with_ai(), не змінюючи решту коду.

На першому етапі замість реального TTS для кожної сцени створюється
"беззвучний" аудіофайл потрібної тривалості. Він відіграє роль
placeholder-озвучки і дозволяє перевірити весь монтажний конвеєр
(включно з синхронізацією за тривалістю сцен) без жодного зовнішнього API.
"""

import os
import subprocess

from backend import ai

SAMPLE_RATE = 44100


def _run_ffmpeg(args: list):
    result = subprocess.run(["ffmpeg", "-y", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg помилка (озвучка): {result.stderr.decode(errors='ignore')}")


def generate_voice_for_scene(scene: dict, output_path: str, language: str = "uk") -> str:
    """Створює аудіофайл озвучки для однієї сцени."""
    ai_result = ai.generate_voice_with_ai(scene["voice_text"], output_path, language)
    if ai_result is not None:
        return ai_result

    duration = scene["duration"]
    _run_ffmpeg([
        "-f", "lavfi",
        "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
        "-t", str(duration),
        output_path,
    ])
    return output_path


def generate_all_voices(scenes: list, output_dir: str, language: str = "uk") -> list:
    """Генерує аудіофайли озвучки для всіх сцен. Повертає список шляхів (у порядку сцен)."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for scene in scenes:
        filename = f"voice_{scene['scene']:02d}.wav"
        path = os.path.join(output_dir, filename)
        generate_voice_for_scene(scene, path, language)
        paths.append(path)
    return paths
