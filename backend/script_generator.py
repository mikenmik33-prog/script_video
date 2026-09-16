"""
Генератор сценарію.

Перетворює тему відео на короткий динамічний сценарій для Shorts/TikTok:
hook -> основна частина -> висновок, автоматично розбитий на сцени.

Використовує Gemini через ai.generate_script_scenes_with_ai. Без ключа або
за помилки API генерація завершується зрозумілою помилкою.

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

SCENE_DURATION = 5  # орієнтовна тривалість однієї сцени, секунди (лише
# початкова оцінка - voice_generator пізніше замінить її на реальну
# тривалість озвучки, щоб відео, аудіо й субтитри збігались ідеально)

def generate_script(topic: str, language: str = "uk") -> dict:
    """Головна функція генерації сценарію та розбиття його на сцени.

    Gemini через ai.py сам вирішує природну кількість сцен під ~25-30с
    озвучки. Локальних шаблонів або резервного сценарію немає.
    """
    scene_texts = ai.generate_script_scenes_with_ai(topic, language)

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

