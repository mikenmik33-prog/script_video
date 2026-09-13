"""
Модуль субтитрів.

- generate_srt(): створює стандартний .srt файл на основі тексту і
  тривалості сцен - окремий артефакт, який користувач отримує разом
  із готовим відео.
- burn_subtitle(): "вписує" текст субтитра у вже згенероване зображення
  сцени - великий читабельний текст, вертикальний кадр, нижня частина
  екрана. Стиль (розмір шрифту, колір, відступ) легко змінити нижче.
"""

import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "DejaVuSans-Bold.ttf")

SUBTITLE_FONT_SIZE = 58
SUBTITLE_TEXT_COLOR = (255, 255, 255)
SUBTITLE_BG_COLOR = (0, 0, 0, 160)
SUBTITLE_MAX_WIDTH_RATIO = 0.85
SUBTITLE_BOTTOM_MARGIN = 260


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


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def burn_subtitle(image_path: str, subtitle_text: str, output_path: str) -> str:
    """Малює субтитр поверх зображення сцени і зберігає результат в output_path."""
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.truetype(FONT_PATH, SUBTITLE_FONT_SIZE)

    max_width = int(width * SUBTITLE_MAX_WIDTH_RATIO)
    lines = _wrap_text(subtitle_text, font, max_width)

    line_height = SUBTITLE_FONT_SIZE + 16
    block_height = line_height * len(lines) + 40
    block_top = height - SUBTITLE_BOTTOM_MARGIN - block_height

    draw.rectangle(
        [(width * 0.05, block_top), (width * 0.95, block_top + block_height)],
        fill=SUBTITLE_BG_COLOR,
    )

    y = block_top + 20
    for line in lines:
        text_width = font.getlength(line)
        x = (width - text_width) / 2
        draw.text((x, y), line, font=font, fill=SUBTITLE_TEXT_COLOR)
        y += line_height

    image.save(output_path)
    return output_path
