"""
Модуль субтитрів.

generate_srt() - створює стандартний .srt файл на основі тексту й
реальної тривалості кожної сцени (voice_generator вимірює її вже після
синтезу озвучки, тому таймінг субтитрів завжди збігається з голосом).

Малювання субтитрів "слово за словом" поверх кадру (для монтажу через
FFmpeg) прибрано разом із editor.py - автоматичний монтаж більше не
використовується (навантажував слабкий сервер), .srt лишається
самостійним файлом для ручного зведення відео.
"""

def _format_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(scenes: list, output_path: str) -> str:
    """Створює .srt файл субтитрів на основі тексту та тривалості сцен."""
    lines = []
    current_time = 0.0
    for i, scene in enumerate(scenes, start=1):
        start = current_time
        end = current_time + scene["duration"]
        lines.append(str(i))
        lines.append(f"{_format_timestamp(start)} --> {_format_timestamp(end)}")
        lines.append(scene["subtitle"])
        lines.append("")
        current_time = end

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path
