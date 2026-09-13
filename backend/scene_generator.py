"""
DEMO-генератор візуалу для сцен.

Система спроєктована так, щоб пізніше можна було підключити будь-який
API генерації зображень або відео - достатньо реалізувати
ai.generate_visual_with_ai(), не змінюючи решту коду.

На першому етапі для кожної сцени створюється локальне тестове
зображення 1080x1920 (кольоровий фон + підпис сцени).
"""

import os

from PIL import Image, ImageDraw, ImageFont

from backend import ai

WIDTH, HEIGHT = 1080, 1920

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", "DejaVuSans-Bold.ttf")

# Кольорові палітри для різних стилів відео (верхній і нижній колір градієнта)
STYLE_PALETTES = {
    "cinematic": [(20, 24, 38), (44, 52, 84)],
    "minimal": [(245, 245, 245), (225, 225, 225)],
    "energetic": [(255, 87, 34), (255, 152, 0)],
    "news": [(30, 30, 30), (120, 20, 20)],
}
DEFAULT_STYLE = "cinematic"


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
    """Створює одне тестове зображення для сцени і зберігає його на диск."""
    ai_result = ai.generate_visual_with_ai(scene["visual_prompt"], output_path)
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


def generate_all_scenes(scenes: list, style: str, output_dir: str) -> list:
    """Генерує зображення для всіх сцен. Повертає список шляхів до файлів (у порядку сцен)."""
    os.makedirs(output_dir, exist_ok=True)
    paths = []
    for scene in scenes:
        filename = f"scene_{scene['scene']:02d}.png"
        path = os.path.join(output_dir, filename)
        generate_scene_image(scene, style, path)
        paths.append(path)
    return paths
