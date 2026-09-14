"""
Генератор озвучки.

Спочатку пробує реальний безкоштовний TTS (edge-tts, через ai.py).
Якщо він недоступний (немає бібліотеки, немає інтернету, збій
запиту), для сцени створюється "беззвучний" аудіофайл орієнтовної
тривалості - це дозволяє конвеєру працювати навіть повністю офлайн.

Незалежно від джерела (реальний голос чи тиша), після генерації
завжди вимірюється РЕАЛЬНА тривалість файлу через ffprobe і
записується назад у scene["duration"]. Це головний механізм, який
робить відео, аудіо й субтитри синхронізованими: довжина сцени в
монтажі (editor.py) і таймінг субтитрів (subtitles.py) визначаються
вже після цього кроку, тобто по фактичній довжині озвучки.
"""

import os
import subprocess

from backend import ai

SAMPLE_RATE = 44100

# невелика пауза після кожної репліки, щоб озвучка не звучала "впритул"
SCENE_PADDING_SECONDS = 0.3


def _run_ffmpeg(args: list):
    result = subprocess.run(["ffmpeg", "-y", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg помилка (озвучка): {result.stderr.decode(errors='ignore')}")


def _probe_duration_seconds(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe помилка: {result.stderr.decode(errors='ignore')}")
    return float(result.stdout.decode().strip())


def _generate_silent_placeholder(duration: float, output_path: str):
    # тиша генерується одразу з відступом (duration вже включає padding),
    # тому окремий прохід для padding тут не потрібен - менше запусків
    # FFmpeg = менше навантаження на CPU (важливо на слабких безкоштовних
    # хостингах)
    _run_ffmpeg([
        "-f", "lavfi",
        "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo",
        "-t", str(duration + SCENE_PADDING_SECONDS),
        "-c:a", "libmp3lame",
        "-q:a", "9",
        output_path,
    ])


def _apply_end_padding(path: str, padding_seconds: float):
    """Додає padding_seconds тиші в кінець аудіофайлу (на місці).

    Робимо це для КОЖНОГО файлу (і реальної озвучки, і тестової тиші),
    щоб реальна тривалість файлу завжди точно збігалася зі
    scene["duration"] - інакше склеєна аудіодоріжка в editor.py
    поступово "розʼїжджалася" б із відео та субтитрами.
    """
    padded_path = f"{path}.padded.mp3"
    _run_ffmpeg([
        "-i", path,
        "-af", f"apad=pad_dur={padding_seconds}",
        "-c:a", "libmp3lame",
        padded_path,
    ])
    os.replace(padded_path, path)


def generate_voice_for_scene(scene: dict, output_path: str, language: str = "uk") -> bool:
    """Створює аудіофайл озвучки для однієї сцени та оновлює scene["duration"]
    реальною тривалістю цього файлу (озвучка + невелика пауза).

    Повертає True, якщо це РЕАЛЬНА озвучка, або False, якщо edge-tts не
    вдався і сцену довелось заповнити тишею (виклик має повідомити про
    це користувачу - раніше такий збій губився тихо в логах сервера)."""
    ai_result = ai.generate_voice_with_ai(scene["voice_text"], output_path, language)
    if ai_result is None:
        _generate_silent_placeholder(scene["duration"], output_path)
        succeeded = False
    else:
        # тривалість реальної озвучки наперед невідома - додаємо
        # відступ окремим (єдиним) проходом
        _apply_end_padding(output_path, SCENE_PADDING_SECONDS)
        succeeded = True

    scene["duration"] = round(_probe_duration_seconds(output_path), 2)
    return succeeded


def generate_all_voices(scenes: list, output_dir: str, language: str = "uk") -> tuple:
    """Генерує аудіофайли озвучки для всіх сцен (мутує scene["duration"]
    кожної сцени реальною тривалістю). Повертає (шляхи, кількість_сцен_із_тишею).

    Навмисно ПОСЛІДОВНО, не паралельно - на відміну від картинок
    (scene_generator), кілька одночасних WebSocket-з'єднань до edge-tts
    виявились ненадійними (запит тихо провалювався, і сцена без жодної
    помилки в UI отримувала беззвучну заглушку замість реального
    голосу). Озвучка й так відносно швидка порівняно з картинками,
    тому послідовність тут не критична для загального часу."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    silent_count = 0
    for scene in scenes:
        filename = f"voice_{scene['scene']:02d}.mp3"
        path = os.path.join(output_dir, filename)
        if not generate_voice_for_scene(scene, path, language):
            silent_count += 1
        paths.append(path)
    return paths, silent_count
