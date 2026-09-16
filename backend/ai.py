"""
Централізований модуль для роботи із зовнішніми AI-сервісами.

Це єдине місце, яке потрібно буде змінити, коли підключатимуться нові
AI-сервіси.

- Сценарій (текст + детальний промт сцени + рекомендований промт руху
  камери): Google Gemini API (потрібен GEMINI_API_KEY).
- Озвучка: edge-tts — зовнішній сервіс синтезу мовлення Microsoft Edge.
- Картинки й відео: застосунок НЕ генерує ні те, ні інше (за рішенням
  користувача - платна генерація картинок через fal.ai виявилась
  зайвим кроком). Замість цього кожна сцена має готовий детальний
  текстовий промт (visual_prompt) і рекомендований промт руху камери
  (motion_prompt, підбирає Gemini з backend/camera_movements.py) -
  користувач сам вставляє їх у Google Flow (чи інший text-to-video
  інструмент) і отримує готове відео напряму.
- Перехід у наступну сцену: Gemini для кожної сцени також обирає
  рекомендований промт переходу (transition_prompt, з
  backend/transitions.py) - підказка, як саме змонтувати цю сцену з
  наступною (hard cut, match cut, cross-dissolve тощо), яку користувач
  застосовує вручну у своєму відеоредакторі.

Якщо AI-виклик не вдається (немає ключа, немає інтернету, збій
відповіді), відповідна функція піднімає зрозумілу помилку. Застосунок
не переходить на локальні шаблони чи заглушки.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

from backend.camera_movements import CAMERA_MOVEMENTS, DEFAULT_CAMERA_MOVEMENT
from backend.transitions import DEFAULT_TRANSITION, SCENE_TRANSITIONS

try:
    import edge_tts
except ImportError:
    edge_tts = None

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT_SECONDS = 60

# Українські та англійські нейронні голоси edge-tts (безкоштовно, без ключа)
EDGE_TTS_VOICES = {
    "uk": "uk-UA-PolinaNeural",
    "en": "en-US-AriaNeural",
}


def _strip_code_fence(text: str) -> str:
    """Прибирає markdown-обгортку навколо JSON, якщо модель її додала."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_script_prompt(topic: str, language: str) -> str:
    language_instruction = "українською мовою" if language == "uk" else "in English"

    if language == "uk":
        number_format_instruction = (
            "- voice_text - текст для озвучки голосом. Усі числа тут пиши "
            "словами, не цифрами, у правильній граматичній формі за "
            "контекстом (наприклад: «333» -> «триста тридцять три», але "
            "«у 333 році» -> «у триста тридцять третьому році», "
            "«5 хвилин» -> «п'ять хвилин»).\n"
        )
        subtitle_instruction = (
            "- subtitle - ТОЧНО ТОЙ САМИЙ текст, слово в слово, що й "
            "voice_text, БЕЗ жодних перефразувань, синонімів чи інших слів - "
            "єдина дозволена відмінність: числа тут пиши звичайними цифрами "
            "замість слів (наприклад «333», «1986 рік», «5 хвилин»), як їх "
            "зазвичай пишуть у субтитрах. Не вигадуй нові слова чи "
            "формулювання, яких немає у voice_text.\n"
        )
        json_example = (
            '[{"voice_text": "У тисяча дев\'ятсот вісімдесят шостому році...", '
            '"subtitle": "У 1986 році...", "camera_movement": "crash_zoom_in", '
            '"transition": "zoom_punch_transition", '
            '"character_appears": true, '
            '"visual_prompt": "A cramped Soviet nuclear power plant control '
            'room at night, rows of analog dials and switches on a heavy '
            'metal console, dim flickering red warning lights casting long '
            'shadows, thin haze in the air, tense claustrophobic atmosphere, '
            'photorealistic cinematic film still, vertical 9:16 composition. '
            'Miki stands beside the console, wide-eyed and alarmed, pointing '
            'at a blinking red gauge."}]'
        )
        # сценарій і так українською - окремий переклад не потрібен
        translation_instruction = ""
        translation_field_example = ""
    else:
        number_format_instruction = (
            "- voice_text - the narration text. ALL numbers here must be "
            "written out as WORDS, in natural spoken English, using the way "
            "numbers are normally read aloud depending on context (e.g. "
            "\"333\" -> \"three hundred thirty-three\", but a year like "
            "\"1986\" -> \"nineteen eighty-six\", \"5 minutes\" -> \"five "
            "minutes\").\n"
        )
        subtitle_instruction = (
            "- subtitle - the EXACT SAME text, word for word, as voice_text, "
            "with NO paraphrasing, synonyms or different wording - the ONLY "
            "allowed difference: write numbers here as plain digits instead "
            "of words (e.g. \"333\", \"1986\", \"5 minutes\"), the way "
            "numbers are normally written in subtitles. Do not invent new "
            "words or phrasing that isn't in voice_text.\n"
        )
        json_example = (
            '[{"voice_text": "In nineteen eighty-six...", '
            '"subtitle": "In 1986...", "camera_movement": "crash_zoom_in", '
            '"transition": "zoom_punch_transition", '
            '"character_appears": true, '
            '"visual_prompt": "A cramped Soviet nuclear power plant control '
            'room at night, rows of analog dials and switches on a heavy '
            'metal console, dim flickering red warning lights casting long '
            'shadows, thin haze in the air, tense claustrophobic atmosphere, '
            'photorealistic cinematic film still, vertical 9:16 composition. '
            'Miki stands beside the console, wide-eyed and alarmed, pointing '
            'at a blinking red gauge.", '
            '"translation_uk": "У тисяча дев\'ятсот вісімдесят шостому році..."}]'
        )
        # сценарій НЕ українською - додатково просимо переклад кожної
        # репліки українською лише для показу користувачу на сторінці
        # (на синтез голосу чи субтитри це не впливає - там і далі мова
        # voice_text/subtitle, обрана користувачем)
        translation_instruction = (
            "- translation_uk - переклад ЦЬОГО voice_text українською "
            "мовою, лише для ознайомлення (не впливає на озвучку чи "
            "субтитри).\n"
        )
        translation_field_example = ', "translation_uk": "..."'

    return (
        "Ти сценарист коротких вертикальних відео (YouTube Shorts/TikTok). "
        f"Напиши текст озвучки {language_instruction} для відео на тему: \"{topic}\". "
        "ЖОРСТКИЙ ЛІМІТ: сумарно ВСІ voice_text усіх сцен РАЗОМ мають "
        "містити НЕ БІЛЬШЕ 80 СЛІВ (орієнтовно 65-80 слів) - при "
        "звичайному темпі озвучки це природно займає ~25-30 секунд. "
        "Це найважливіше обмеження - навіть якщо тема велика й хочеться "
        "розповісти більше, обери лише найважливіші факти й вклад йся в "
        "ліміт слів, а НЕ намагайся вмістити все. Перевищення ліміту "
        "неприпустиме. Водночас протягом УСЬОГО відео постійно має щось "
        "розповідатися - без штучних пауз чи розтягнутих речень. "
        "Розбий текст на ПРИРОДНУ кількість сцен, яку підказує сам зміст "
        "(зазвичай 4-7) - кожна сцена має містити достатньо змісту, щоб "
        "озвучка цієї сцени звучала природно завершеною думкою, а не "
        "штучним обривком. "
        "Перша сцена - сильний hook, що одразу чіпляє увагу. "
        "Остання сцена - короткий висновок і заклик підписатись. "
        "Без зайвої води, без вступних фраз на кшталт «звісно» чи «добре». "
        "Для кожної сцени поверни ці поля:\n"
        f"{number_format_instruction}"
        f"{subtitle_instruction}"
        f"{translation_instruction}"
        "- camera_movement - оціни ДІЮ саме цієї сцени (спокійна розповідь, "
        "різкий поворот сюжету, наближення до важливої деталі, рух/погоня, "
        "огляд великого простору тощо) і поверни ОДНЕ слово-ключ зі списку "
        f"нижче, яке найкраще передає САМЕ ЦЮ дію (не бери одне й те саме "
        "для кожної сцени підряд, лише якщо дія справді однакова): "
        f"{', '.join(CAMERA_MOVEMENTS.keys())}.\n"
        "- transition - як САМЕ ЦЯ сцена має перетекти в НАСТУПНУ сцену "
        "(для останньої сцени - як завершити відео). Дивись на зміст ОБОХ "
        "сцен (цієї й наступної): чи продовжується той самий предмет/дія "
        "(тоді підійде плавний match cut), чи тема різко змінюється (тоді "
        "простий hard cut), чи потрібен спокійний перехід через зміну "
        "настрою/епохи (cross-dissolve), чи навпаки динамічний/тривожний "
        "момент (whip pan чи zoom punch), чи це список/порівняння "
        "(slide wipe), чи сильний емоційний акцент/панчлайн (flash cut). "
        "Поверни ОДНЕ слово-ключ зі списку, яке найкраще передає САМЕ ЦЕЙ "
        f"перехід (не бери одне й те саме підряд без причини): "
        f"{', '.join(SCENE_TRANSITIONS.keys())}.\n"
        "- character_appears - true/false: чи має в цій сцені з'явитися "
        "постійний персонаж-провідник відео на ім'я Miki. Miki НЕ повинен "
        "бути в кожній сцені - вирішуй по суті: він природно пасує сценам "
        "з реакцією/коментарем/емоцією (подив, тривога, ентузіазм), "
        "hook-сцені й фінальній сцені із закликом підписатись, але НЕ "
        "пасує сценам, що просто показують факт/об'єкт/місце без потреби "
        "в людській реакції на нього. Розподіли true/false логічно по "
        "сценах (не всі true, не всі false).\n"
        "- visual_prompt - детальний ОПИС СЦЕНИ англійською мовою для "
        "AI text-to-video генератора (користувач вставляє цей текст "
        "напряму в Google Flow чи інший подібний інструмент і отримує "
        "готове відео сцени - ЦЕ ЄДИНИЙ візуальний опис, ніякого "
        "проміжного фото немає, тому промт має бути самодостатнім і "
        "детальним): що саме відбувається в цій КОНКРЕТНІЙ сцені "
        "(предмет, місце дії, дія, атмосфера, освітлення). "
        "ПЕРЕД тим як писати visual_prompt, визнач ГОЛОВНУ ДУМКУ саме цього "
        "voice_text (який конкретний факт/подія/аргумент розповідається "
        "зараз, а не тема відео загалом) - і зобрази САМЕ ЇЇ, а не загальну "
        "абстрактну ілюстрацію теми відео чи просто «настрій». Наприклад, "
        "якщо voice_text розповідає про зниклий корабель - на картинці має "
        "бути саме корабель (чи його слід), а не просто хвилі; якщо "
        "розповідається про конкретну цифру чи порівняння - картинка "
        "повинна візуально показувати саме цей факт/масштаб, а не абстрактну "
        "картинку теми. ЦЕ СТОСУЄТЬСЯ І ПЕРШОЇ (hook) СЦЕНИ - навіть якщо "
        "voice_text цієї сцени лише загальна фраза на кшталт «чому це "
        "важливо», картинка ВСЕ ОДНО має показувати конкретний предмет/"
        "місце/об'єкт САМЕ З ТЕМИ ВІДЕО (наприклад для теми про Бермудський "
        "трикутник - корабель, океан, компас, карта, а НЕ вигадані сторонні "
        "образи типу озброєних людей, які не мають стосунку до теми). "
        "Ніколи не додавай у visual_prompt предмети чи персонажів, яких "
        "немає в самій темі відео чи voice_text цієї сцени. Усі сцени разом "
        "мають розповідати ту саму історію, "
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
        "atmosphere\" - інакше сцена втрачає драматизм тексту. Кожна сцена "
        "повинна "
        "мати ВІЗУАЛЬНО РІЗНИЙ промт (різні предмети/ракурси/деталі), а "
        "не варіації одного й того самого кадру. Це промт для генерації "
        "відео, а НЕ переклад voice_text. Без жодного "
        "тексту/літер/цифр/водяних знаків у кадрі. Вертикальна "
        "композиція (9:16), обов'язково кінематографічний стиль: глибина "
        "кадру, якість кінокадру (film still), а не проста ілюстрація. "
        "Головний обʼєкт сцени завжди має бути ЧІТКО ВИДНИЙ і ДОБРЕ "
        "ОСВІТЛЕНИЙ - уникай суцільного силуету, надмірної темряви чи "
        "густого туману, які роблять обʼєкт нерозбірливим.\n"
        "Персонаж Miki: якщо character_appears для цієї сцени true - "
        "використовуй незмінний дизайн персонажа: молодий на вигляд 2D "
        "мультяшний хлопець середнього зросту (176 см), світла шкіра, "
        "скуйовджене світло-русяве волосся, чорний довгий верх, сині "
        "джинси й чорне взуття, товстий чорний контур. Він має виглядати "
        "як 2D-персонаж, органічно вставлений у реалістичний "
        "кінематографічний світ; не додавай білий фон, не змінюй одяг, "
        "пропорції чи стиль без прямої потреби сюжету. "
        "visual_prompt МАЄ прямо називати його на ім'я (\"Miki\") і "
        "описувати одним реченням його конкретну дію/позу/вираз обличчя, "
        "що відповідає змісту репліки (наприклад \"Miki stands beside "
        "the console, wide-eyed and alarmed, pointing at the gauge\"). "
        "Якщо character_appears false - visual_prompt НЕ повинен "
        "згадувати Miki чи будь-якого іншого персонажа-провідника "
        "взагалі - лише сцена/фон.\n"
        "visual_prompt МАЄ бути детальним - МІНІМУМ 3-4 речення, що "
        "разом покривають: (1) головний предмет/суб'єкт з конкретними "
        "візуальними деталями (форма, колір, матеріал, стан), (2) "
        "оточення/місце дії з деталями фону, (3) освітлення й кольорову "
        "гаму, (4) загальну атмосферу/настрій сцени. Кожна деталь має "
        "бути ОБҐРУНТОВАНА змістом сцени - не вигадуй додаткових "
        "персонажів, предметів чи елементів, яких немає в описі сцени, "
        "лише щоб промт виглядав багатше. Кожен ГОЛОВНИЙ об'єкт сцени "
        "має бути "
        "згаданий РІВНО ОДИН РАЗ і чітко (наприклад один літак - не "
        "\"a plane\" і окремо ще раз натяком на другий літак чи крило "
        "збоку) - двозначні чи повторювані згадки одного предмета "
        "змушують генератор зображень домальовувати зайву копію цього "
        "предмета в кадрі. "
        "Візуал МАЄ ТОЧНО відповідати конкретним деталям з voice_text, а не "
        "узагальненому предмету тієї ж категорії - якщо voice_text називає "
        "конкретний тип/модель/призначення предмета (наприклад «військовий "
        "бомбардувальник ВМС», «вантажний корабель», «винищувач») - на "
        "картинці має бути саме він (військовий літак з відповідними "
        "розпізнавальними ознаками, а НЕ звичайний цивільний пасажирський "
        "літак типу Boeing/Airbus); якщо називається просто «літак» без "
        "уточнень - тоді підійде і цивільний. Якщо voice_text згадує "
        "конкретний рік/епоху - все на картинці (одяг, транспорт, "
        "технології, архітектура) має відповідати САМЕ ТІЙ епосі, а не "
        "сучасності (наприклад «у 1943 році» -> техніка й форма часів "
        "Другої світової, а не сучасна); якщо йдеться про сучасність чи рік "
        "не вказано - показуй сучасні речі.\n"
        "Поверни ВИКЛЮЧНО JSON-масив об'єктів (кількість елементів = "
        'кількість сцен, яку ти сам визначив) формату {"voice_text": "...", '
        '"subtitle": "...", "camera_movement": "...", "transition": "...", '
        '"character_appears": '
        f'true/false, "visual_prompt": "..."{translation_field_example}}}, '
        f"без markdown і без пояснень. Приклад: {json_example}"
    )


def _extract_gemini_text(body: dict) -> str:
    """Extract generated text from a Gemini generateContent response."""
    for candidate in body.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise RuntimeError("Gemini не повернув текстову відповідь.")


def _call_gemini(prompt: str) -> str:
    scene_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "voice_text": {"type": "string"},
                "subtitle": {"type": "string"},
                "camera_movement": {"type": "string"},
                "transition": {"type": "string"},
                "character_appears": {"type": "boolean"},
                "visual_prompt": {"type": "string"},
                "translation_uk": {"type": "string"},
            },
            "required": [
                "voice_text",
                "subtitle",
                "camera_movement",
                "transition",
                "character_appears",
                "visual_prompt",
                "translation_uk",
            ],
        },
    }
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": scene_schema,
        },
    }).encode("utf-8")

    request = urllib.request.Request(
        GEMINI_URL.format(model=GEMINI_MODEL),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        logger.warning("Gemini script API HTTP %s: %s", exc.code, details[:2000])
        raise

    return _extract_gemini_text(body)


MIN_SCENES, MAX_SCENES = 3, 9
# Жорсткий ліміт слів у сумі всіх voice_text - інструкція в промті
# просить Gemini дотримуватись ~65-80 слів (природно ~25-30с озвучки),
# але LLM не завжди точно дотримується власних інструкцій, тому
# додатково перевіряємо результат кодом і відхиляємо занадто довгий
# сценарій (замість реального ризику отримати відео на кілька хвилин
# замість заявлених 30 секунд) - MAX з великим запасом над орієнтиром.
MAX_TOTAL_WORDS = 110


def generate_script_scenes_with_ai(topic: str, language: str):
    """Генерує текст і промт візуалу для кожної сцени через Google Gemini API.

    Gemini сам вирішує, скільки сцен потрібно (орієнтовно 25-30с
    озвучки загалом) - кількість НЕ фіксується наперед.

    Повертає список словників {"voice_text", "subtitle", "visual_prompt", ...}.
    Якщо ключ відсутній або Gemini повертає некоректну відповідь, піднімає
    помилку: застосунок не підміняє реальний результат тестовим сценарієм.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("Не задано GEMINI_API_KEY. Додайте ключ у файл .env і перезапустіть сервер.")

    try:
        prompt = _build_script_prompt(topic, language)
        raw_text = _call_gemini(prompt)
        scenes = json.loads(_strip_code_fence(raw_text))

        if not isinstance(scenes, list) or not (MIN_SCENES <= len(scenes) <= MAX_SCENES):
            raise RuntimeError("Gemini повернув некоректну кількість сцен. Спробуйте іншу тему.")

        total_words = sum(len(str(scene.get("voice_text", "")).split()) for scene in scenes)
        if total_words > MAX_TOTAL_WORDS:
            raise RuntimeError(
                f"Gemini повернув надто довгий сценарій ({total_words} слів; максимум {MAX_TOTAL_WORDS}). Спробуйте іншу тему."
            )

        result = []
        for scene in scenes:
            voice_text = str(scene["voice_text"]).strip()
            subtitle = str(scene.get("subtitle", voice_text)).strip()
            visual_prompt = str(scene.get("visual_prompt", topic)).strip()
            camera_movement_key = str(scene.get("camera_movement", "")).strip()
            if camera_movement_key not in CAMERA_MOVEMENTS:
                camera_movement_key = DEFAULT_CAMERA_MOVEMENT
            transition_key = str(scene.get("transition", "")).strip()
            if transition_key not in SCENE_TRANSITIONS:
                transition_key = DEFAULT_TRANSITION
            entry = {
                "voice_text": voice_text,
                "subtitle": subtitle,
                "visual_prompt": visual_prompt,
                "motion_prompt": CAMERA_MOVEMENTS[camera_movement_key],
                "transition_prompt": SCENE_TRANSITIONS[transition_key],
                "character_appears": bool(scene.get("character_appears", False)),
            }
            if language != "uk":
                # переклад лише для показу на сторінці - якщо Gemini з
                # якоїсь причини не повернув поле, показуємо оригінал,
                # а не ламаємо весь результат
                entry["translation_uk"] = str(scene.get("translation_uk", voice_text)).strip()
            result.append(entry)
        return result
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Gemini API недоступний: %s", exc)
        raise RuntimeError("Gemini API недоступний або повернув некоректну відповідь. Перевірте ключ і спробуйте ще раз.") from exc


async def _synthesize_with_edge_tts(text: str, voice: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_voice_with_ai(text: str, output_path: str, language: str):
    """Синтезує озвучку через edge-tts (безкоштовно, без API-ключа).

    Повертає шлях до збереженого mp3-файлу. За помилки синтезу піднімає
    виняток, щоб не підміняти озвучку беззвучним файлом.
    """
    if edge_tts is None:
        raise RuntimeError("Пакет edge-tts не встановлений. Встановіть залежності з requirements.txt.")

    voice = EDGE_TTS_VOICES.get(language, EDGE_TTS_VOICES["uk"])
    try:
        asyncio.run(_synthesize_with_edge_tts(text, voice, output_path))
        return output_path
    except Exception as exc:  # мережа/сервіс edge-tts можуть бути недоступні
        logger.warning("edge-tts недоступний: %s", exc)
        raise RuntimeError("Сервіс озвучки edge-tts недоступний. Спробуйте ще раз.") from exc
