"""
DEMO-генератор сценарію.

Перетворює тему відео на короткий динамічний сценарій для Shorts/TikTok:
hook -> основна частина -> висновок, автоматично розбитий на сцени.

Спочатку пробує реальний AI (ai.generate_script_with_ai). Якщо API-ключ
не налаштований (DEMO-режим), використовується локальний шаблонний
генератор нижче - він не залежить від жодного зовнішнього сервісу.
"""

from backend import ai

SCENE_DURATION = 5  # орієнтовна тривалість однієї сцени, секунди

TRANSITIONS = ["fade", "cut", "slide"]

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


def _split_duration(total_duration: int, scene_count: int) -> list:
    """Ділить загальну тривалість на цілочисельні шматки, що в сумі дають total_duration."""
    base = total_duration // scene_count
    remainder = total_duration - base * scene_count
    durations = [base] * scene_count
    for i in range(remainder):
        durations[i] += 1
    return durations


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


def generate_script(topic: str, duration: int, language: str = "uk") -> dict:
    """Головна функція генерації сценарію та розбиття його на сцени.

    Спочатку пробує реальний AI (Gemini, через ai.py). Якщо ключа немає
    або запит не вдався, використовує локальний DEMO-шаблон - обидва
    варіанти дають однакову кількість сцен і однаковий формат виводу.
    """
    scene_count = max(3, round(duration / SCENE_DURATION))
    durations = _split_duration(duration, scene_count)

    ai_lines = ai.generate_script_lines_with_ai(topic, scene_count, language)
    if ai_lines is not None:
        lines = ai_lines
    else:
        template = _get_template(language)
        lines = _build_lines(topic, template, scene_count)

    scenes = []
    for index, (text, scene_duration) in enumerate(zip(lines, durations), start=1):
        visual_prompt = f"{topic} - {'сцена' if language == 'uk' else 'scene'} {index}"
        scenes.append({
            "scene": index,
            "duration": scene_duration,
            "voice_text": text,
            "visual_prompt": visual_prompt,
            "subtitle": text,
            "transition": TRANSITIONS[(index - 1) % len(TRANSITIONS)],
        })

    return {
        "topic": topic,
        "language": language,
        "duration": duration,
        "full_text": " ".join(lines),
        "scenes": scenes,
    }
