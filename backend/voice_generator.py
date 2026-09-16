"""
Генератор озвучки.

Використовує edge-tts через ai.py. Якщо сервіс недоступний, генерація
завершується помилкою без створення беззвучного файла.

Після генерації завжди вимірюється РЕАЛЬНА тривалість файла через ffprobe і
записується назад у scene["duration"]. Це головний механізм, який
робить відео, аудіо й субтитри синхронізованими: довжина сцени в
монтажі (editor.py) і таймінг субтитрів (subtitles.py) визначаються
вже після цього кроку, тобто по фактичній довжині озвучки.
"""

import os
import subprocess

from backend import ai

# невелика пауза після кожної репліки, щоб озвучка не звучала "впритул"
SCENE_PADDING_SECONDS = 0.3

# Google Flow (і подібні text-to-video інструменти) генерують кліпи
# ЛИШЕ фіксованої тривалості - 4, 6 чи 8 секунд, не довільної. Реальна
# тривалість озвучки (до сотих секунди) лишається в scene["duration"]
# для точної синхронізації субтитрів, а це - лише підказка користувачу,
# яку тривалість вибрати в самому Flow під цю сцену.
FLOW_DURATIONS = (4, 6, 8)


def _nearest_flow_duration(seconds: float) -> int:
    return min(FLOW_DURATIONS, key=lambda d: abs(d - seconds))


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

    Повертає True після успішної реальної озвучки. За помилки синтезу
    піднімає виняток і не створює беззвучну підміну."""
    ai_result = ai.generate_voice_with_ai(scene["voice_text"], output_path, language)
    # тривалість реальної озвучки наперед невідома - додаємо відступ окремим
    # (єдиним) проходом.
    _apply_end_padding(ai_result, SCENE_PADDING_SECONDS)

    scene["duration"] = round(_probe_duration_seconds(output_path), 2)
    scene["flow_duration"] = _nearest_flow_duration(scene["duration"])
    return True


def generate_all_voices(scenes: list, output_dir: str, language: str = "uk") -> tuple:
    """Генерує аудіофайли озвучки для всіх сцен (мутує scene["duration"]
    кожної сцени реальною тривалістю). Повертає (шляхи, 0).

    Навмисно ПОСЛІДОВНО, не паралельно - кілька одночасних
    WebSocket-з'єднань до edge-tts виявились ненадійними."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for scene in scenes:
        filename = f"voice_{scene['scene']:02d}.mp3"
        path = os.path.join(output_dir, filename)
        generate_voice_for_scene(scene, path, language)
        paths.append(path)
    return paths, 0

