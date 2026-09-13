"""
Модуль субтитрів.

- generate_srt(): створює стандартний .srt файл на основі тексту і
  тривалості сцен - окремий артефакт, який користувач отримує разом
  із готовим відео.
- generate_word_highlight_frames(): для однієї сцени малює НАБІР кадрів
  (по одному на кожне слово субтитру) поверх зображення сцени - у
  кожному кадрі підсвічене саме те слово, яке в цей момент "звучить".
  Тривалість показу кожного слова пропорційна його довжині (символам),
  тож підсвічування рухається природно навіть без точного пословного
  таймінгу з TTS. Текст малюється з чорним обведенням, без фонової
  підложки - сучасний "субтитровий" вигляд.
"""

import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "DejaVuSans-Bold.ttf")

SUBTITLE_FONT_SIZE = 58
SUBTITLE_TEXT_COLOR = (255, 255, 255)
SUBTITLE_HIGHLIGHT_COLOR = (255, 209, 51)  # жовтий акцент для активного слова
SUBTITLE_OUTLINE_COLOR = (0, 0, 0)
SUBTITLE_OUTLINE_WIDTH = 5
SUBTITLE_MAX_WIDTH_RATIO = 0.85
SUBTITLE_BOTTOM_MARGIN = 260
SUBTITLE_LINE_SPACING = 16

# мінімальна тривалість показу одного слова, сек (щоб дуже короткі
# слова на кшталт "і", "в" не блимали занадто швидко)
MIN_WORD_DISPLAY_SECONDS = 0.12


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


def _wrap_words(words: list, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """Розбиває слова на рядки (список списків слів), не змінюючи сам текст -
    розбивка рахується один раз і однакова для всіх кадрів однієї сцени."""
    space_width = font.getlength(" ")
    lines, current, current_width = [], [], 0
    for word in words:
        word_width = font.getlength(word)
        added = word_width if not current else word_width + space_width
        if current and current_width + added > max_width:
            lines.append(current)
            current, current_width = [word], word_width
        else:
            current.append(word)
            current_width += added
    if current:
        lines.append(current)
    return lines


def _compute_word_durations(words: list, total_duration: float) -> list:
    """Ділить total_duration між словами пропорційно до їхньої довжини
    (символів), з мінімальною тривалістю на слово."""
    if not words:
        return []
    raw = [max(len(w), 1) for w in words]
    total_raw = sum(raw)
    durations = [total_duration * r / total_raw for r in raw]

    # гарантуємо мінімальну тривалість, компенсуючи за рахунок найдовшого слова
    for i, d in enumerate(durations):
        if d < MIN_WORD_DISPLAY_SECONDS and len(durations) > 1:
            deficit = MIN_WORD_DISPLAY_SECONDS - d
            longest_i = max(range(len(durations)), key=lambda j: durations[j])
            if longest_i != i:
                durations[longest_i] -= deficit
                durations[i] = MIN_WORD_DISPLAY_SECONDS
    return durations


def _render_frame(base_image: Image.Image, lines: list, active_line: int, active_word: int, output_path: str):
    image = base_image.copy()
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, SUBTITLE_FONT_SIZE)
    width, height = image.size

    line_height = SUBTITLE_FONT_SIZE + SUBTITLE_LINE_SPACING
    block_height = line_height * len(lines)
    y = height - SUBTITLE_BOTTOM_MARGIN - block_height
    space_width = font.getlength(" ")

    for line_index, line_words in enumerate(lines):
        line_width = sum(font.getlength(w) for w in line_words) + space_width * (len(line_words) - 1)
        x = (width - line_width) / 2
        for word_index, word in enumerate(line_words):
            is_active = line_index == active_line and word_index == active_word
            color = SUBTITLE_HIGHLIGHT_COLOR if is_active else SUBTITLE_TEXT_COLOR
            draw.text(
                (x, y), word, font=font, fill=color,
                stroke_width=SUBTITLE_OUTLINE_WIDTH, stroke_fill=SUBTITLE_OUTLINE_COLOR,
            )
            x += font.getlength(word) + space_width
        y += line_height

    # BMP - без стиснення, значно швидше за PNG для проміжних кадрів,
    # яких на одну сцену може бути десятки (важливо на слабких CPU)
    image.convert("RGB").save(output_path, "BMP")


def generate_word_highlight_frames(image_path: str, subtitle_text: str, duration: float, work_dir: str, prefix: str) -> list:
    """Створює для сцени послідовність кадрів "слово за словом".

    Повертає список (шлях_до_кадру, тривалість_показу) у порядку показу,
    що в сумі дають рівно `duration`.
    """
    base_image = Image.open(image_path).convert("RGB")
    font = ImageFont.truetype(FONT_PATH, SUBTITLE_FONT_SIZE)
    max_width = int(base_image.width * SUBTITLE_MAX_WIDTH_RATIO)

    words = subtitle_text.split()
    if not words:
        static_path = f"{work_dir}/{prefix}_static.bmp"
        base_image.save(static_path, "BMP")
        return [(static_path, duration)]

    lines = _wrap_words(words, font, max_width)
    durations = _compute_word_durations(words, duration)

    frames = []
    global_index = 0
    for line_index, line_words in enumerate(lines):
        for word_index in range(len(line_words)):
            frame_path = os.path.join(work_dir, f"{prefix}_{global_index:03d}.bmp")
            _render_frame(base_image, lines, line_index, word_index, frame_path)
            frames.append((frame_path, durations[global_index]))
            global_index += 1
    return frames
