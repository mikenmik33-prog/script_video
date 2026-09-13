"""
Централізований модуль для роботи із зовнішніми AI-сервісами.

Це єдине місце, яке потрібно буде змінити, коли підключатимуться нові
AI-сервіси (наприклад платна генерація зображень/відео).

- Сценарій: Gemini API (потрібен GEMINI_API_KEY, безкоштовний).
- Озвучка: edge-tts - безкоштовний, без API-ключа (використовує
  публічний сервіс синтезу мовлення Microsoft Edge). Це неофіційна
  бібліотека, тому за потреби легко замінити на офіційний платний TTS
  (Google Cloud TTS, Azure тощо) - для цього просто впиши TTS_API_KEY
  та реалізуй виклик у generate_voice_with_ai() за тим самим принципом.

Якщо будь-який AI-виклик не вдається (немає ключа, немає інтернету,
збій відповіді) - відповідна generate_*_with_ai() повертає None, і
викликач (script_generator / voice_generator) переходить на локальну
DEMO-заглушку. Це гарантує, що застосунок ніколи не "падає" через
проблеми з зовнішнім сервісом.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

try:
    import edge_tts
except ImportError:
    edge_tts = None

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "").strip()
TTS_API_KEY = os.getenv("TTS_API_KEY", "").strip()

GEMINI_MODEL = "gemini-flash-lite-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_TIMEOUT_SECONDS = 30

# Українські та англійські нейронні голоси edge-tts (безкоштовно, без ключа)
EDGE_TTS_VOICES = {
    "uk": "uk-UA-PolinaNeural",
    "en": "en-US-AriaNeural",
}

DEMO_MODE = not (OPENAI_API_KEY or GEMINI_API_KEY or VIDEO_API_KEY or TTS_API_KEY)


def has_text_api() -> bool:
    return bool(OPENAI_API_KEY or GEMINI_API_KEY)


def has_visual_api() -> bool:
    return bool(VIDEO_API_KEY)


def has_voice_api() -> bool:
    return edge_tts is not None or bool(TTS_API_KEY)


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
        "Для кожної сцени поверни ДВА варіанти тексту:\n"
        "- voice_text - текст для озвучки голосом. Усі числа тут пиши "
        "словами, не цифрами, у правильній граматичній формі за "
        "контекстом (наприклад: «333» -> «триста тридцять три», але "
        "«у 333 році» -> «у триста тридцять третьому році», "
        "«5 хвилин» -> «п'ять хвилин»).\n"
        "- subtitle - той самий текст для субтитрів на екрані, але "
        "числа тут пиши звичайними цифрами (наприклад «333», «1986 рік», "
        "«5 хвилин»), як їх зазвичай пишуть у субтитрах.\n"
        f"Поверни ВИКЛЮЧНО JSON-масив довжиною {scene_count} з об'єктів "
        'формату {"voice_text": "...", "subtitle": "..."}, без markdown '
        "і без пояснень. Приклад: "
        '[{"voice_text": "У тисяча дев\'ятсот вісімдесят шостому році...", '
        '"subtitle": "У 1986 році..."}]'
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


def generate_script_scenes_with_ai(topic: str, scene_count: int, language: str):
    """Генерує текст сцен (окремо voice_text і subtitle) через Gemini API.

    Повертає список словників {"voice_text": ..., "subtitle": ...}
    довжиною scene_count, або None - якщо ключа немає чи запит не
    вдався (тоді script_generator використовує локальний DEMO-шаблон).
    """
    if not GEMINI_API_KEY:
        return None

    try:
        prompt = _build_script_prompt(topic, scene_count, language)
        raw_text = _call_gemini(prompt)
        scenes = json.loads(_strip_code_fence(raw_text))

        if not isinstance(scenes, list) or len(scenes) != scene_count:
            logger.warning("Gemini повернув невірну кількість сцен, використовуємо DEMO-шаблон")
            return None

        result = []
        for scene in scenes:
            voice_text = str(scene["voice_text"]).strip()
            subtitle = str(scene.get("subtitle", voice_text)).strip()
            result.append({"voice_text": voice_text, "subtitle": subtitle})
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini API недоступний (%s), використовуємо DEMO-шаблон", exc)
        return None


def generate_visual_with_ai(prompt: str, output_path: str):
    """Місце для підключення реального генератора зображень/відео.

    Повертає шлях до збереженого файлу або None, якщо ключа немає.
    """
    if not has_visual_api():
        return None
    raise NotImplementedError("Реальний API генерації візуалу ще не підключено")


async def _synthesize_with_edge_tts(text: str, voice: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_voice_with_ai(text: str, output_path: str, language: str):
    """Синтезує озвучку через edge-tts (безкоштовно, без API-ключа).

    Повертає шлях до збереженого mp3-файлу, або None - якщо бібліотека
    не встановлена чи запит не вдався (тоді voice_generator створює
    тестову тишу потрібної тривалості).
    """
    if edge_tts is None:
        return None

    voice = EDGE_TTS_VOICES.get(language, EDGE_TTS_VOICES["uk"])
    try:
        asyncio.run(_synthesize_with_edge_tts(text, voice, output_path))
        return output_path
    except Exception as exc:  # мережа/сервіс edge-tts можуть бути недоступні
        logger.warning("edge-tts недоступний (%s), використовуємо тестову тишу", exc)
        return None
