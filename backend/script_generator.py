"""
Генератор сценарію.

Перетворює тему відео на короткий динамічний сценарій для Shorts/TikTok:
hook -> основна частина -> висновок, автоматично розбитий на сцени.

Спочатку пробує реальний AI (ai.generate_script_scenes_with_ai, Gemini).
Якщо ключа немає або запит не вдався, використовується локальний
шаблонний генератор нижче - він не залежить від жодного зовнішнього
сервісу.

Кожна сцена містить: voice_text (для озвучки - числа словами), subtitle
(для екрану - числа цифрами), visual_prompt (детальний опис сцени
англійською - користувач сам вставляє його в Google Flow чи інший
text-to-video інструмент), motion_prompt (готовий рекомендований промт
руху камери, Gemini сам обирає найбільш підходящий варіант зі списку в
backend/camera_movements.py під дію конкретної сцени) і transition_prompt
(готовий рекомендований промт переходу в наступну сцену, Gemini обирає
з backend/transitions.py, враховуючи зміст обох сцен). "duration" на
цьому етапі лише орієнтовна оцінка - voice_generator пізніше замінить
її на реальну тривалість згенерованої озвучки.

Тривалість відео користувач більше не обирає - Gemini сам вирішує,
скільки сцен потрібно, розраховуючи текст на природних ~25-30 секунд
озвучки (без штучних пауз чи розтягувань заради конкретної цифри).
"""

from backend import ai
from backend.camera_movements import CAMERA_MOVEMENTS, DEFAULT_CAMERA_MOVEMENT
from backend.transitions import DEFAULT_TRANSITION, SCENE_TRANSITIONS

SCENE_DURATION = 5  # орієнтовна тривалість однієї сцени, секунди (лише
# початкова оцінка - voice_generator пізніше замінить її на реальну
# тривалість озвучки, щоб відео, аудіо й субтитри збігались ідеально)

# Лише для DEMO-шаблону (коли немає GEMINI_API_KEY чи запит не вдався) -
# реальний AI сам вирішує кількість сцен, орієнтуючись на зміст
DEMO_SCENE_COUNT = 6

TEMPLATES = {
    "uk": {
        "hook": "Що станеться, якщо {topic}? Зараз розберемось.",
        "body": [
            "Спочатку варто зрозуміти, чому це взагалі важливо.",
            "Уявіть, наскільки сильно це вплинуло б на звичне життя.",
            "Науковці вже давно замислюються над подібними питаннями.",
            "Але є нюанс, про який мало хто говорить.",
            "Наслідки можуть бути набагато серйознішими, ніж здається.",
            "І це лише вершина айсберга.",
            "Деякі експерти взагалі вважають це неминучим.",
            "А тепер найцікавіше.",
        ],
        "conclusion": "Ось чому тема «{topic}» варта того, щоб про неї думати. Підписуйся, щоб не пропустити більше цікавого!",
    },
    "en": {
        "hook": "What would happen if {topic}? Let's find out.",
        "body": [
            "First, it's worth understanding why this even matters.",
            "Imagine how much this would change everyday life.",
            "Scientists have been thinking about questions like this for years.",
            "But there's a detail almost nobody talks about.",
            "The consequences could be far more serious than they seem.",
            "And this is just the tip of the iceberg.",
            "Some experts even think it's inevitable.",
            "Now here's the most interesting part.",
        ],
        "conclusion": "That's why \"{topic}\" is worth thinking about. Subscribe for more videos like this!",
    },
}


def _get_template(language: str) -> dict:
    return TEMPLATES.get(language, TEMPLATES["uk"])


def _build_lines(topic: str, template: dict, scene_count: int) -> list:
    # hook-шаблон сам додає "?" в кінці - прибираємо зайву пунктуацію з теми,
    # якщо користувач уже сформулював її як питання
    hook_topic = topic.rstrip("?!. ")
    lines = [template["hook"].format(topic=hook_topic)]

    body_pool = template["body"]
    body_needed = max(scene_count - 2, 0)
    for i in range(body_needed):
        sentence = body_pool[i % len(body_pool)]
        lines.append(sentence)

    lines.append(template["conclusion"].format(topic=topic))
    return lines


def generate_script(topic: str, language: str = "uk") -> dict:
    """Головна функція генерації сценарію та розбиття його на сцени.

    Спочатку пробує реальний AI (Gemini, через ai.py) - той сам вирішує
    природну кількість сцен під ~25-30с озвучки. Якщо ключа немає або
    запит не вдався, використовує локальний DEMO-шаблон (фіксована
    кількість сцен - DEMO_SCENE_COUNT).
    """
    ai_scenes_text = ai.generate_script_scenes_with_ai(topic, language)
    if ai_scenes_text is not None:
        scene_texts = ai_scenes_text
    else:
        template = _get_template(language)
        lines = _build_lines(topic, template, DEMO_SCENE_COUNT)
        # DEMO-шаблон не має ні чисел, ні реального промта від AI:
        # voice_text/subtitle однакові, а visual_prompt - проста заглушка
        scene_texts = [
            {
                "voice_text": line, "subtitle": line,
                "visual_prompt": f"{topic}, scene {i}",
                "motion_prompt": CAMERA_MOVEMENTS[DEFAULT_CAMERA_MOVEMENT],
                "transition_prompt": SCENE_TRANSITIONS[DEFAULT_TRANSITION],
                "character_appears": False,
            }
            for i, line in enumerate(lines, start=1)
        ]

    scenes = []
    for index, texts in enumerate(scene_texts, start=1):
        scene = {
            "scene": index,
            "duration": SCENE_DURATION,  # орієнтовно - voice_generator замінить реальною тривалістю
            "voice_text": texts["voice_text"],
            "visual_prompt": texts["visual_prompt"],
            "motion_prompt": texts["motion_prompt"],
            "transition_prompt": texts["transition_prompt"],
            "character_appears": texts.get("character_appears", False),
            "subtitle": texts["subtitle"],
        }
        if "translation_uk" in texts:
            scene["translation_uk"] = texts["translation_uk"]
        scenes.append(scene)

    result = {
        "topic": topic,
        "language": language,
        "full_text": " ".join(s["voice_text"] for s in scenes),
        "scenes": scenes,
    }
    # переклад для показу на сторінці - лише коли сценарій НЕ українською
    # (не впливає на озвучку/субтитри, ті лишаються обраною мовою)
    if language != "uk" and all("translation_uk" in s for s in scenes):
        result["full_text_uk"] = " ".join(s["translation_uk"] for s in scenes)
    return result
