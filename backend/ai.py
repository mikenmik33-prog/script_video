"""
Централізований модуль для роботи із зовнішніми AI-сервісами.

Це єдине місце, яке потрібно буде змінити, коли підключатимуться платні
API (генерація зображень/відео, TTS). Текстова частина (сценарій) вже
підключена до безкоштовного Gemini API - якщо задати GEMINI_API_KEY,
сценарій писатиме реальна AI-модель; якщо ключа немає (або стався
збій запиту) - викликач (script_generator) переходить на локальний
DEMO-шаблон.

generate_visual_with_ai() та generate_voice_with_ai() поки залишаються
заглушками з тим самим принципом: реалізуй функцію - і решта коду
підхопить реальний сервіс без жодних змін деінде.
"""

import json
import logging
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "").strip()
TTS_API_KEY = os.getenv("TTS_API_KEY", "").strip()

GEMINI_MODEL = "gemini-1.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_TIMEOUT_SECONDS = 30

DEMO_MODE = not (OPENAI_API_KEY or GEMINI_API_KEY or VIDEO_API_KEY or TTS_API_KEY)


def has_text_api() -> bool:
    return bool(OPENAI_API_KEY or GEMINI_API_KEY)


def has_visual_api() -> bool:
    return bool(VIDEO_API_KEY)


def has_voice_api() -> bool:
    return bool(TTS_API_KEY)


def _strip_code_fence(text: str) -> str:
    """Gemini часто обгортає JSON у ```json ... ``` - прибираємо це."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_script_prompt(topic: str, scene_count: int, language: str) -> str:
    language_instruction = "українською мовою" if language == "uk" else "in English"
    return (
        "Ти сценарист коротких вертикальних відео (YouTube Shorts/TikTok). "
        f"Напиши текст озвучки {language_instruction} для відео на тему: \"{topic}\". "
        f"Розбий текст рівно на {scene_count} сцен. "
        "Перша сцена - сильний hook, що одразу чіпляє увагу. "
        "Остання сцена - короткий висновок і заклик підписатись. "
        "Без зайвої води, без вступних фраз на кшталт «звісно» чи «добре». "
        f"Поверни ВИКЛЮЧНО JSON-масив рядків довжиною {scene_count} "
        "(один текст на одну сцену), без markdown і без пояснень. "
        'Приклад формату: ["Текст сцени 1", "Текст сцени 2"]'
    )


def _call_gemini(prompt: str) -> str:
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9},
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))

    return body["candidates"][0]["content"]["parts"][0]["text"]


def generate_script_lines_with_ai(topic: str, scene_count: int, language: str):
    """Генерує текст озвучки для кожної сцени через Gemini API.

    Повертає список рядків довжиною scene_count, або None - якщо
    ключа немає чи запит не вдався (тоді script_generator
    використовує локальний DEMO-шаблон).
    """
    if not GEMINI_API_KEY:
        return None

    try:
        prompt = _build_script_prompt(topic, scene_count, language)
        raw_text = _call_gemini(prompt)
        lines = json.loads(_strip_code_fence(raw_text))

        if not isinstance(lines, list) or len(lines) != scene_count:
            logger.warning("Gemini повернув невірну кількість сцен, використовуємо DEMO-шаблон")
            return None

        return [str(line).strip() for line in lines]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.warning("Gemini API недоступний (%s), використовуємо DEMO-шаблон", exc)
        return None


def generate_visual_with_ai(prompt: str, output_path: str):
    """Місце для підключення реального генератора зображень/відео.

    Повертає шлях до збереженого файлу або None, якщо ключа немає.
    """
    if not has_visual_api():
        return None
    raise NotImplementedError("Реальний API генерації візуалу ще не підключено")


def generate_voice_with_ai(text: str, output_path: str, language: str):
    """Місце для підключення реального TTS API.

    Повертає шлях до збереженого аудіофайлу або None, якщо ключа немає.
    """
    if not has_voice_api():
        return None
    raise NotImplementedError("Реальний TTS API ще не підключено")
