"""
Генератор візуалу для сцен.

Спочатку пробує реальну генерацію зображення через ai.py (Pollinations.ai,
за промтом visual_prompt від Gemini + стильовий суфікс нижче). Якщо
запит не вдався (немає інтернету, сервіс недоступний), для сцени
створюється тестове кольорове зображення 720x1280 з підписом - це
дозволяє конвеєру працювати навіть повністю офлайн.
"""

import logging
import os

from PIL import Image, ImageDraw, ImageFont

from backend import ai

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 720, 1280  # 720p

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "DejaVuSans-Bold.ttf")

# Кольорові палітри для різних стилів відео (верхній і нижній колір градієнта) -
# використовуються лише в офлайн-заглушці, якщо реальна генерація не вдалась
STYLE_PALETTES = {
    "cinematic": [(20, 24, 38), (44, 52, 84)],
    "minimal": [(245, 245, 245), (225, 225, 225)],
    "energetic": [(255, 87, 34), (255, 152, 0)],
    "news": [(30, 30, 30), (120, 20, 20)],
}
DEFAULT_STYLE = "cinematic"

# Додається до visual_prompt від AI, щоб зображення відповідало обраному стилю відео
STYLE_PROMPT_SUFFIXES = {
    "cinematic": "cinematic lighting, dramatic, film still, high detail",
    "minimal": "minimalist, clean, flat design, simple shapes, soft colors",
    "energetic": "vibrant colors, dynamic, high energy, bold composition",
    "news": "photorealistic, documentary style, serious tone, neutral lighting",
}


def _gradient_background(style: str, scene_index: int) -> Image.Image:
    top, bottom = STYLE_PALETTES.get(style, STYLE_PALETTES[DEFAULT_STYLE])

    # невеликий зсув відтінку залежно від номера сцени, щоб сцени візуально відрізнялись
    shift = (scene_index * 9) % 40
    top = tuple(min(255, c + shift) for c in top)

    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    return image


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


def _draw_centered_lines(draw: ImageDraw.ImageDraw, lines: list, font: ImageFont.FreeTypeFont, color, center_y: int):
    line_height = font.size + 14
    total_height = line_height * len(lines)
    y = center_y - total_height // 2
    for line in lines:
        width = font.getlength(line)
        x = (WIDTH - width) / 2
        draw.text((x, y), line, font=font, fill=color)
        y += line_height


def generate_scene_image(scene: dict, style: str, output_path: str) -> str:
    """Створює одне зображення для сцени і зберігає його на диск."""
    style_suffix = STYLE_PROMPT_SUFFIXES.get(style, STYLE_PROMPT_SUFFIXES[DEFAULT_STYLE])
    # "cinematic composition, professional lighting" додається завжди,
    # незалежно від обраного стилю - кожна картинка має виглядати
    # кінематографічно, а стиль лише додає свій відтінок зверху
    full_prompt = (
        f"{scene['visual_prompt']}, cinematic composition, professional lighting, "
        f"{style_suffix}, vertical 9:16, no text, no watermark"
    )

    ai_result = ai.generate_visual_with_ai(full_prompt, output_path)
    if ai_result is not None:
        return ai_result

    image = _gradient_background(style, scene["scene"])
    draw = ImageDraw.Draw(image)

    label_font = ImageFont.truetype(FONT_PATH, 44)
    prompt_font = ImageFont.truetype(FONT_PATH, 80)

    text_color = (40, 40, 40) if style == "minimal" else (255, 255, 255)

    draw.text((60, 70), f"СЦЕНА {scene['scene']}", font=label_font, fill=text_color)

    lines = _wrap_text(scene["visual_prompt"], prompt_font, WIDTH - 160)
    _draw_centered_lines(draw, lines, prompt_font, text_color, HEIGHT // 2)

    image.save(output_path)
    return output_path


def generate_all_scenes(scenes: list, style: str, output_dir: str, progress_callback=None) -> list:
    """Генерує зображення для всіх сцен. Повертає список шляхів до файлів (у порядку сцен).

    progress_callback(fraction: 0..1) - необов'язковий, викликається
    після кожної сцени. Реальна генерація зображення - це мережевий
    запит і може займати кілька секунд на сцену, тому без цього
    прогрес-бар виглядав би "завислим" на весь час цього етапу.
    """
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for i, scene in enumerate(scenes, start=1):
        filename = f"scene_{scene['scene']:02d}.png"
        path = os.path.join(output_dir, filename)
        generate_scene_image(scene, style, path)
        paths.append(path)
        if progress_callback is not None:
            progress_callback(i / len(scenes))

    # ТИМЧАСОВИЙ діагностичний виклик: пробуємо оживити відео саме
    # першої (hero) сцени через Kling AI - результат ще НЕ впливає на
    # фінальне відео (лише зберігається поруч, у _kling_test.mp4), це
    # окрема перевірка, чи сам виклик API взагалі працює, перш ніж
    # вплітати його в монтаж.
    if ai.has_kling_api() and scenes:
        first_scene = scenes[0]
        test_output = os.path.join(output_dir, "scene_01_kling_test.mp4")
        logger.info("KLING TEST: пробуємо згенерувати відео для сцени 1...")
        result = ai.generate_video_clip_with_ai(paths[0], first_scene["visual_prompt"], test_output)
        if result is not None:
            logger.info("KLING TEST: УСПІХ, відео збережено в %s", result)
        else:
            logger.warning("KLING TEST: НЕ ВДАЛОСЯ (див. попередження вище з причиною)")

    return paths
