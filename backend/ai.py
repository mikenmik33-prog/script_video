"""
Централізований модуль для роботи із зовнішніми AI-сервісами.

Це єдине місце, яке потрібно буде змінити, коли підключатимуться платні
API (текстова модель для сценарію, генерація зображень/відео, TTS).

На першому етапі (DEMO) ключів немає, тому всі generate_*_with_ai()
повертають None - виклик, що їх викликав (script_generator,
scene_generator, voice_generator), у відповідь використовує свій
локальний DEMO-генератор. Інтерфейс функцій вже розрахований на те,
що пізніше сюди можна буде вписати реальні запити без зміни решти коду.
"""

import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VIDEO_API_KEY = os.getenv("VIDEO_API_KEY", "").strip()
TTS_API_KEY = os.getenv("TTS_API_KEY", "").strip()

DEMO_MODE = not (OPENAI_API_KEY or VIDEO_API_KEY or TTS_API_KEY)


def has_text_api() -> bool:
    return bool(OPENAI_API_KEY)


def has_visual_api() -> bool:
    return bool(VIDEO_API_KEY)


def has_voice_api() -> bool:
    return bool(TTS_API_KEY)


def generate_script_with_ai(topic: str, duration: int, language: str):
    """Місце для підключення реальної текстової моделі (напр. OpenAI).

    Повертає готовий словник сценарію (такого ж формату, як
    script_generator.generate_script) або None, якщо ключа немає -
    тоді викликається DEMO-генератор.
    """
    if not has_text_api():
        return None
    raise NotImplementedError("Реальний текстовий API ще не підключено")


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
