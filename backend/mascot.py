"""
Еталонні зображення персонажа-маскота застосунку.

Персонаж - незмінний намальований (лінійний, "стик-фігура") герой,
який має з'являтися в кожній сцені кожного відео, завжди з однаковим
дизайном (коло-голова, палички тіла/рук/ніг, примітивне, але читабельне
обличчя), у позі, що відповідає дії сцени.

Щоб AI-генератор зображень (fal.ai) "запам'ятав" цей точний дизайн, а
не вигадував його наново щоразу, дизайн спершу тренується як окрема
LoRA-модель (backend/ai.py, submit_mascot_lora_training) на наборі
еталонних зображень. Ці еталонні зображення НАВМИСНО малюються самим
кодом (PIL), а не AI - так дизайн гарантовано однаковий у кожній позі
(жодних "AI трохи по-іншому намалював цього разу"), а вже далі LoRA
переносить саме цей точний дизайн у реалістичні AI-згенеровані сцени.

Це не фінальний вигляд персонажа в готовому відео - це лише навчальний
матеріал для LoRA.
"""

import os

from PIL import Image, ImageDraw

CANVAS_SIZE = (512, 768)
BG_COLOR = (255, 255, 255, 255)
LINE_COLOR = (20, 20, 20, 255)
LINE_WIDTH = 10

HEAD_RADIUS = 55
HEAD_CENTER = (256, 170)
SHOULDER = (256, 260)
HIP = (256, 430)

# Кожна поза: rel-координати (dx, dy) від SHOULDER для кожної руки і від
# HIP для кожної ноги (кінцева точка кисті/стопи; лікті/коліна не
# моделюємо окремо - для такого примітивного стилю пряма лінія
# читається краще за "зламану").
POSES = {
    "neutral_standing": {
        "arm_left": (-90, 140), "arm_right": (90, 140),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "neutral",
    },
    "waving": {
        "arm_left": (-90, 140), "arm_right": (120, -60),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "happy",
    },
    "pointing_forward": {
        "arm_left": (-90, 140), "arm_right": (170, 10),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "neutral",
    },
    "arms_up_excited": {
        "arm_left": (-120, -80), "arm_right": (120, -80),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "excited",
    },
    "arms_crossed": {
        "arm_left": (70, 10), "arm_right": (-70, 50),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "skeptical",
    },
    "walking": {
        "arm_left": (-100, 90), "arm_right": (110, 100),
        "leg_left": (-100, 190), "leg_right": (100, 210),
        "face": "neutral",
    },
    "thinking": {
        "arm_left": (-90, 140), "arm_right": (25, -95),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "thinking",
    },
    "shrug": {
        "arm_left": (-110, -20), "arm_right": (110, -20),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "shrug",
    },
    "thumbs_up": {
        "arm_left": (-90, 140), "arm_right": (100, -30),
        "leg_left": (-70, 200), "leg_right": (70, 200),
        "face": "happy",
    },
    "surprised_jump": {
        "arm_left": (-110, -100), "arm_right": (110, -100),
        "leg_left": (-50, 170), "leg_right": (50, 170),
        "face": "surprised",
    },
}


def _draw_face(draw: ImageDraw.ImageDraw, style: str):
    eye_y = HEAD_CENTER[1] - 5
    left_eye = (HEAD_CENTER[0] - 20, eye_y)
    right_eye = (HEAD_CENTER[0] + 20, eye_y)
    eye_r = 5

    for eye in (left_eye, right_eye):
        draw.ellipse(
            [eye[0] - eye_r, eye[1] - eye_r, eye[0] + eye_r, eye[1] + eye_r],
            fill=LINE_COLOR,
        )

    brow_y = eye_y - 22
    brow_half_w = 16
    # brow_tilt: позитивне - "здивовано/схвильовано" (брови вгору),
    # від'ємне - "скептично/невдоволено" (брови вниз до перенісся)
    brow_tilt = {
        "neutral": 0, "happy": 4, "excited": 10, "skeptical": -10,
        "thinking": -6, "shrug": 6, "surprised": 14,
    }[style]
    for side, eye in ((-1, left_eye), (1, right_eye)):
        inner = (eye[0] - side * brow_half_w, brow_y + (brow_tilt if side < 0 else -brow_tilt) * 0.4)
        outer = (eye[0] + side * brow_half_w, brow_y - (brow_tilt if side < 0 else -brow_tilt) * 0.6)
        draw.line([inner, outer], fill=LINE_COLOR, width=6)

    mouth_cx, mouth_y = HEAD_CENTER[0], HEAD_CENTER[1] + 28
    if style == "happy":
        draw.arc([mouth_cx - 24, mouth_y - 14, mouth_cx + 24, mouth_y + 14], 20, 160, fill=LINE_COLOR, width=6)
    elif style == "excited" or style == "surprised":
        r = 14 if style == "excited" else 11
        draw.ellipse([mouth_cx - r, mouth_y - r, mouth_cx + r, mouth_y + r], outline=LINE_COLOR, width=6)
    elif style == "skeptical":
        draw.line([(mouth_cx - 18, mouth_y + 6), (mouth_cx + 18, mouth_y - 4)], fill=LINE_COLOR, width=6)
    elif style == "thinking" or style == "shrug":
        draw.line([(mouth_cx - 16, mouth_y), (mouth_cx + 16, mouth_y)], fill=LINE_COLOR, width=6)
    else:  # neutral
        draw.line([(mouth_cx - 18, mouth_y), (mouth_cx + 18, mouth_y)], fill=LINE_COLOR, width=6)


def draw_pose(pose_name: str, output_path: str) -> str:
    """Малює одну еталонну позу персонажа і зберігає як PNG. Повертає output_path."""
    pose = POSES[pose_name]

    image = Image.new("RGBA", CANVAS_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(image)

    hx, hy = HEAD_CENTER
    draw.ellipse(
        [hx - HEAD_RADIUS, hy - HEAD_RADIUS, hx + HEAD_RADIUS, hy + HEAD_RADIUS],
        outline=LINE_COLOR, width=LINE_WIDTH,
    )

    neck_top = (hx, hy + HEAD_RADIUS)
    draw.line([neck_top, SHOULDER], fill=LINE_COLOR, width=LINE_WIDTH)
    draw.line([SHOULDER, HIP], fill=LINE_COLOR, width=LINE_WIDTH)

    for dx, dy in (pose["arm_left"], pose["arm_right"]):
        draw.line([SHOULDER, (SHOULDER[0] + dx, SHOULDER[1] + dy)], fill=LINE_COLOR, width=LINE_WIDTH)
    for dx, dy in (pose["leg_left"], pose["leg_right"]):
        draw.line([HIP, (HIP[0] + dx, HIP[1] + dy)], fill=LINE_COLOR, width=LINE_WIDTH)

    _draw_face(draw, pose["face"])

    image.save(output_path)
    return output_path


def generate_reference_set(output_dir: str) -> list:
    """Генерує ВСІ еталонні пози в output_dir. Повертає список (назва_пози, шлях)."""
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for pose_name in POSES:
        path = os.path.join(output_dir, f"{pose_name}.png")
        draw_pose(pose_name, path)
        results.append((pose_name, path))
    return results
