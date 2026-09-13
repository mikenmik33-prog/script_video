"""
Централізований модуль для роботи із зовнішніми AI-сервісами.

Це єдине місце, яке потрібно буде змінити, коли підключатимуться нові
AI-сервіси (наприклад платна генерація зображень/відео вищої якості).

- Сценарій (текст + промти сцен): Gemini API (потрібен GEMINI_API_KEY,
  безкоштовний).
- Візуал: Hugging Face Inference API (модель FLUX.1-schnell) -
  безкоштовно, без водяного знаку (це прямий вивід моделі, без
  сервісного логотипу), потрібен безкоштовний HUGGINGFACE_API_KEY.
  Резервного варіанту свідомо немає - Pollinations.ai пробували
  раніше, але він завжди додає водяний знак (навіть з токеном), тому
  чесна відмова (тестове зображення) краща за тихе підсовування
  картинки з чужим логотипом. Якщо Hugging Face недоступний -
  generate_visual_with_ai() повертає None.
  Примітка: генерація зображень безпосередньо через Gemini ("Nano
  Banana") існує, але на безкоштовному тарифі Gemini її квота
  дорівнює нулю (потрібен платний білінг).
- Озвучка: edge-tts - безкоштовний, без API-ключа (використовує
  публічний сервіс синтезу мовлення Microsoft Edge). Це неофіційна
  бібліотека, тому за потреби легко замінити на офіційний платний TTS
  (Google Cloud TTS, Azure тощо) - для цього просто впиши TTS_API_KEY
  та реалізуй виклик у generate_voice_with_ai() за тим самим принципом.
- Відео для окремих сцен (не обов'язково для всіх): fal.ai (платний,
  потрібен FAL_API_KEY) - image-to-video через модель MiniMax Hailuo,
  оживляє вже згенероване зображення сцени рухом. Оплата за фактичне
  використання, без підписки чи мінімального платежу (на відміну від
  Kling AI Open Platform, де мінімальний корпоративний тариф
  починається від $1550/міс - для нашого вибіркового, нечастого
  використання це не підходить). Викликається вибірково, не для
  кожної сцени - див. scene_generator.py.

Якщо будь-який AI-виклик не вдається (немає ключа, немає інтернету,
збій відповіді) - відповідна generate_*_with_ai() повертає None, і
викликач (script_generator / scene_generator / voice_generator)
переходить на локальну DEMO-заглушку. Це гарантує, що застосунок
ніколи не "падає" через проблеми з зовнішнім сервісом.
"""

import asyncio
import base64
import json
import logging
import os
import random
import time
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
FAL_API_KEY = os.getenv("FAL_API_KEY", "").strip()
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "").strip()

GEMINI_MODEL = "gemini-flash-lite-latest"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_TIMEOUT_SECONDS = 30

# fal.ai - агрегатор AI-моделей з оплатою за фактичне використання
# (queue-based API: POST у чергу -> опитування статусу -> результат)
FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_MODEL = "fal-ai/minimax/hailuo-2.3-fast/standard/image-to-video"
# скільки максимум чекати результату - рахує викликач (server.py) за
# часом від моменту постановки в чергу, порівнюючи із submitted_at
FAL_MAX_WAIT_SECONDS = 180

IMAGE_WIDTH, IMAGE_HEIGHT = 720, 1280  # 720p - має збігатися з editor.py/scene_generator.py

HUGGINGFACE_MODEL = "black-forest-labs/FLUX.1-schnell"
HUGGINGFACE_TIMEOUT_SECONDS = 60

# Українські та англійські нейронні голоси edge-tts (безкоштовно, без ключа)
EDGE_TTS_VOICES = {
    "uk": "uk-UA-PolinaNeural",
    "en": "en-US-AriaNeural",
}

DEMO_MODE = not (OPENAI_API_KEY or GEMINI_API_KEY or VIDEO_API_KEY or TTS_API_KEY)


def has_text_api() -> bool:
    return bool(OPENAI_API_KEY or GEMINI_API_KEY)


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
        "Для кожної сцени поверни ТРИ поля:\n"
        "- voice_text - текст для озвучки голосом. Усі числа тут пиши "
        "словами, не цифрами, у правильній граматичній формі за "
        "контекстом (наприклад: «333» -> «триста тридцять три», але "
        "«у 333 році» -> «у триста тридцять третьому році», "
        "«5 хвилин» -> «п'ять хвилин»).\n"
        "- subtitle - ТОЧНО ТОЙ САМИЙ текст, слово в слово, що й "
        "voice_text, БЕЗ жодних перефразувань, синонімів чи інших слів - "
        "єдина дозволена відмінність: числа тут пиши звичайними цифрами "
        "замість слів (наприклад «333», «1986 рік», «5 хвилин»), як їх "
        "зазвичай пишуть у субтитрах. Не вигадуй нові слова чи "
        "формулювання, яких немає у voice_text.\n"
        "- visual_prompt - детальний ОПИС КАРТИНКИ англійською мовою для "
        "AI-генератора зображень: що саме має бути зображено в цій "
        "КОНКРЕТНІЙ сцені (предмет, місце дії, дія, атмосфера, освітлення). "
        "ПЕРЕД тим як писати visual_prompt, визнач ГОЛОВНУ ДУМКУ саме цього "
        "voice_text (який конкретний факт/подія/аргумент розповідається "
        "зараз, а не тема відео загалом) - і зобрази САМЕ ЇЇ, а не загальну "
        "абстрактну ілюстрацію теми відео чи просто «настрій». Наприклад, "
        "якщо voice_text розповідає про зниклий корабель - на картинці має "
        "бути саме корабель (чи його слід), а не просто хвилі; якщо "
        "розповідається про конкретну цифру чи порівняння - картинка "
        "повинна візуально показувати саме цей факт/масштаб, а не абстрактну "
        "картинку теми. Усі сцени разом мають розповідати ту саму історію, "
        "що й сценарій, у тій самій послідовності - наступна сцена логічно "
        "продовжує попередню (не стрибає на випадкову деталь теми), а не "
        "просто повторює загальну атмосферу. Якщо сцена описує щось "
        "небезпечне, руйнівне чи катастрофічне (вибух, аварія, загроза, "
        "катастрофа) - промт МАЄ передавати саме відчуття небезпеки й хаосу, "
        "а НЕ виглядати як спокійна, естетично гарна чи мальовнича картинка "
        "(генератор зображень за замовчуванням тяжіє саме до \"гарного\", "
        "тому це треба прописати явно словами). Використовуй в англійському "
        "тексті конкретні слова дії й руйнування на кшталт: violent, "
        "turbulent, chaotic, powerful blast/shockwave, debris flying, "
        "destruction, ominous, dangerous, motion blur - а не лише назву "
        "явища. Наприклад, замість \"underwater explosion of gas bubbles\" "
        "пиши \"violent underwater explosion, massive turbulent shockwave, "
        "chaotic debris blasted upward, powerful dangerous force, ominous "
        "atmosphere\" - інакше сцена втрачає драматизм тексту. Для такої "
        "динамічної/катастрофічної дії показуй саме ПОЧАТКОВИЙ МОМЕНТ "
        "зародження події (перша іскра/тріщина/спалах, вибух лише "
        "починається), а НЕ вже завершений розпал у найвищій точці - "
        "картинка є першим кадром, з якого сцену потім можуть оживити "
        "рухом (image-to-video), а рухатись є куди лише якщо подія на "
        "картинці ще розвивається, а не вже досягла піку. Кожна сцена "
        "повинна "
        "мати ВІЗУАЛЬНО РІЗНИЙ промт (різні предмети/ракурси/деталі), а "
        "не варіації одного й того самого кадру. Це промт для генерації "
        "зображення, а НЕ переклад voice_text. Без жодного "
        "тексту/літер/цифр/водяних знаків на самому зображенні. Вертикальна "
        "композиція (9:16), обов'язково кінематографічний стиль: глибина "
        "кадру, якість кінокадру (film still), а не проста ілюстрація. "
        "Головний обʼєкт сцени завжди має бути ЧІТКО ВИДНИЙ і ДОБРЕ "
        "ОСВІТЛЕНИЙ - уникай суцільного силуету, надмірної темряви чи "
        "густого туману, які роблять обʼєкт нерозбірливим.\n"
        f"Поверни ВИКЛЮЧНО JSON-масив довжиною {scene_count} з об'єктів "
        'формату {"voice_text": "...", "subtitle": "...", "visual_prompt": '
        '"..."}, без markdown і без пояснень. Приклад: '
        '[{"voice_text": "У тисяча дев\'ятсот вісімдесят шостому році...", '
        '"subtitle": "У 1986 році...", "visual_prompt": "A Soviet nuclear '
        'power plant control room at night, dim red warning lights, tense '
        'atmosphere, cinematic, vertical composition"}]'
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
    """Генерує текст і промт візуалу для кожної сцени через Gemini API.

    Повертає список словників {"voice_text", "subtitle", "visual_prompt"}
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
            visual_prompt = str(scene.get("visual_prompt", topic)).strip()
            result.append({
                "voice_text": voice_text,
                "subtitle": subtitle,
                "visual_prompt": visual_prompt,
            })
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini API недоступний (%s), використовуємо DEMO-шаблон", exc)
        return None


def _generate_image_with_huggingface(prompt: str, output_path: str):
    """Генерує зображення через офіційну бібліотеку huggingface_hub.

    Пряме звернення до api-inference.huggingface.co більше не
    підтримується (Hugging Face перейшли на систему Inference
    Providers, де запит автоматично маршрутизується до одного з
    партнерів - fal.ai, replicate тощо) - тому використовуємо їхній
    офіційний клієнт замість "сирого" HTTP-запиту, щоб не залежати
    від внутрішньої логіки маршрутизації, яка може змінюватись.

    Кидає виняток при збої (ловить викликач generate_visual_with_ai)."""
    from huggingface_hub import InferenceClient

    client = InferenceClient(token=HUGGINGFACE_API_KEY, timeout=HUGGINGFACE_TIMEOUT_SECONDS)
    seed = random.randint(0, 2**31 - 1)
    image = client.text_to_image(
        prompt,
        model=HUGGINGFACE_MODEL,
        width=IMAGE_WIDTH,
        height=IMAGE_HEIGHT,
        seed=seed,
    )
    image.save(output_path)
    return output_path


def generate_visual_with_ai(prompt: str, output_path: str):
    """Генерує зображення сцени через Hugging Face Inference API
    (безкоштовно, без водяного знаку).

    Резервний варіант Pollinations.ai свідомо прибрано - він завжди
    додавав водяний знак навіть з токеном, тому "запасний" результат
    був гіршим за чесну відмову. Якщо Hugging Face недоступний -
    повертає None, і scene_generator створює тестове кольорове
    зображення (це одразу видно й зрозуміло, на відміну від тихого
    підсовування картинки з чужим водяним знаком).
    """
    if not HUGGINGFACE_API_KEY:
        return None

    try:
        return _generate_image_with_huggingface(prompt, output_path)
    except Exception as exc:
        logger.warning("Hugging Face недоступний (%s), використовуємо тестове зображення", exc)
        return None


def has_video_api() -> bool:
    return bool(FAL_API_KEY)


def _guess_image_mime(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    return "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"


def _fal_auth_headers() -> dict:
    return {"Authorization": f"Key {FAL_API_KEY}"}


def _log_fal_http_error(exc: "urllib.error.HTTPError", context: str) -> None:
    # тіло відповіді зазвичай містить точний код/причину помилки
    # (наприклад брак балансу, невірний формат запиту тощо) - без
    # цього в логах видно лише голий HTTP-код, замало для діагностики
    try:
        error_body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        error_body = "<не вдалось прочитати тіло відповіді>"
    logger.warning(
        "fal.ai (%s): HTTP %s: %s, тіло відповіді: %s",
        context, exc.code, exc.reason, error_body,
    )


def submit_video_job(image_path: str, prompt: str):
    """Ставить у чергу fal.ai (модель MiniMax Hailuo) запит на
    оживлення зображення коротким відеокліпом (image-to-video) -
    платний сервіс з оплатою за фактичне використання, викликається
    вибірково, не для кожної сцени (див. scene_generator.py).

    Зображення передається як base64 data URI прямо в тілі запиту, щоб
    не залежати від того, чи доступне воно за публічним URL.

    Модель видає 768p, 25fps, БЕЗ звукової доріжки (нам це підходить -
    озвучку й музику ми й так додаємо окремо через ffmpeg). Тривалість
    підтримується лише фіксована - 6 або 10 секунд (не довільна) -
    беремо 6с як дешевший варіант ($0.28 проти $0.56 за кліп).

    Повертає {"status_url", "response_url"} для подальшого опитування
    через check_video_job(), або None - якщо ключа немає чи запит на
    постановку в чергу не вдався.

    Це лише миттєва постановка в чергу (один швидкий HTTP-запит) - сама
    генерація займає хвилини, тому очікування результату винесене в
    окрему функцію (check_video_job), яку викликач опитує самостійно
    (наприклад, у відповідь на періодичні запити від браузера), а не
    один довгий блокуючий цикл на сервері - на слабкому CPU (Render
    free-тариф) багатохвилинний цикл з time.sleep у фоновому потоці
    підвищував ризик примусового рестарту процесу, через що і job, і
    вже сплачений результат генерації губились безповоротно.
    """
    if not FAL_API_KEY:
        return None

    submit_url = f"{FAL_QUEUE_BASE}/{FAL_MODEL}"

    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        image_data_uri = f"data:{_guess_image_mime(image_path)};base64,{image_b64}"

        submit_payload = json.dumps({
            "prompt": prompt,
            "image_url": image_data_uri,
            "duration": "6",
        }).encode("utf-8")

        submit_request = urllib.request.Request(
            submit_url,
            data=submit_payload,
            headers={**_fal_auth_headers(), "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(submit_request, timeout=30) as response:
            submit_body = json.loads(response.read().decode("utf-8"))

        return {
            "status_url": submit_body["status_url"],
            "response_url": submit_body["response_url"],
        }
    except urllib.error.HTTPError as exc:
        _log_fal_http_error(exc, "постановка в чергу")
        return None
    except Exception as exc:
        logger.warning("fal.ai недоступний (%s), лишаємо статичну картинку", exc)
        return None


def check_video_job(status_url: str, response_url: str, output_path: str) -> str:
    """Одна швидка перевірка стану задачі в черзі fal.ai - без сну й
    без циклу очікування (див. docstring submit_video_job для причини).

    Повертає "processing", "done" (кліп уже збережено в output_path)
    або "error".
    """
    try:
        status_request = urllib.request.Request(status_url, headers=_fal_auth_headers())
        with urllib.request.urlopen(status_request, timeout=20) as response:
            status_body = json.loads(response.read().decode("utf-8"))

        status = status_body.get("status")
        if status == "COMPLETED":
            result_request = urllib.request.Request(response_url, headers=_fal_auth_headers())
            with urllib.request.urlopen(result_request, timeout=20) as response:
                result_body = json.loads(response.read().decode("utf-8"))
            video_url = result_body["video"]["url"]
            with urllib.request.urlopen(video_url, timeout=60) as response:
                with open(output_path, "wb") as f:
                    f.write(response.read())
            return "done"
        if status in ("ERROR", "CANCELED"):
            logger.warning("fal.ai: генерація відео завершилась невдало (status=%s)", status)
            return "error"
        return "processing"
    except urllib.error.HTTPError as exc:
        _log_fal_http_error(exc, "перевірка статусу")
        return "error"
    except Exception as exc:
        logger.warning("fal.ai: помилка перевірки статусу (%s)", exc)
        return "error"


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
