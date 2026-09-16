"""
Модуль трендових ідей для відео.

Працюємо в одній фіксованій ніші - цікаві факти, наука/технології та
загадкові/містичні історії (у форматі оповіді про щось цікаве, а не
гейминг/меми/трейлери). Тому замість "просто найпопулярніші відео
YouTube" (chart=mostPopular) шукаємо трендові відео САМЕ в цій ніші
через пошук (search.list за ключовими словами), а тоді підтягуємо
реальну кількість переглядів (videos.list) і сортуємо від найбільшої
до найменшої.

Список ЗАЛЕЖИТЬ ВІД МОВИ, обраної в формі "Новий промт" - для "uk"
шукаємо українською мовою й регіоном UA, для "en" - англійською і
регіоном US (LANGUAGES нижче). Кеші двох мов незалежні одне від
одного.

Це коштує значно дорожчої квоти YouTube API, ніж chart=mostPopular
(search.list = 100 одиниць за виклик, безкоштовна квота - 10 000/добу),
тому фонове оновлення відбувається рідше (раз на кілька годин), а не
щохвилини - обидві мови оновлюються одразу при старті сервера (це і є
"оновлення при заході на сторінку"), а надалі лише вручну кнопкою чи
за фоновим розкладом.

Потрібен YOUTUBE_API_KEY. За відсутності ключа чи помилки API локальні
ідеї не підставляються: клієнт отримує порожній список і опис проблеми.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_TIMEOUT_SECONDS = 20

DEFAULT_LANGUAGE = "uk"

# Ніша: цікаві факти / наука і технології / загадкові історії - усе у
# форматі короткої розповіді "про щось цікаве". Окремі пошукові запити
# й регіон для кожної мови озвучки, щоб стрічка справді показувала
# популярне САМЕ для цієї мовної аудиторії, а не переклад української.
LANGUAGES = {
    "uk": {
        "region": "UA",
        "relevance_language": "uk",
        "niche_queries": ["цікаві факти", "наукові факти", "загадкові історії факти"],
    },
    "en": {
        "region": "US",
        "relevance_language": "en",
        "niche_queries": ["interesting facts", "science facts", "mysterious unsolved stories"],
    },
}

RESULTS_PER_QUERY = 10
MAX_IDEAS = 20

# search.list коштує 100 одиниць квоти за запит (у нас 3 запити на
# оновлення + 1 дешевий videos.list, помножено на 2 мови) - тому
# оновлюємо нечасто, щоб не вичерпати безкоштовну добову квоту
# (10 000 одиниць/добу)
REFRESH_INTERVAL_SECONDS = 3 * 60 * 60  # раз на 3 години

_cache_lock = threading.Lock()
_cached_ideas = {lang: [] for lang in LANGUAGES}
_last_updated = {lang: None for lang in LANGUAGES}


def _normalize_language(language: str) -> str:
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def _search_video_ids(query: str, region: str, relevance_language: str) -> list:
    """Пошук відео за ключовим словом ніші. Повертає список videoId
    (без статистики переглядів - search.list її не дає)."""
    params = {
        "part": "id",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "regionCode": region,
        "relevanceLanguage": relevance_language,
        "maxResults": str(RESULTS_PER_QUERY),
        "key": YOUTUBE_API_KEY,
    }
    url = f"{YOUTUBE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=YOUTUBE_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))

    return [item["id"]["videoId"] for item in body.get("items", []) if item.get("id", {}).get("videoId")]


def _fetch_video_stats(video_ids: list) -> list:
    """Реальна кількість переглядів і мініатюри для списку videoId (одним запитом)."""
    if not video_ids:
        return []

    params = {
        "part": "snippet,statistics",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY,
    }
    url = f"{YOUTUBE_VIDEOS_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=YOUTUBE_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))

    ideas = []
    for item in body.get("items", []):
        title = item["snippet"]["title"]
        views = int(item.get("statistics", {}).get("viewCount", 0))
        thumbnails = item["snippet"].get("thumbnails", {})
        thumbnail = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
        ideas.append({"title": title, "views": views, "thumbnail": thumbnail})
    return ideas


def _fetch_niche_trending(language: str) -> list:
    """Збирає трендові відео ніші (для конкретної мови/регіону) з кількох
    пошукових запитів, прибирає дублікати і сортує від найбільшої
    кількості переглядів до найменшої."""
    cfg = LANGUAGES[language]
    video_ids = []
    seen = set()
    for query in cfg["niche_queries"]:
        for video_id in _search_video_ids(query, cfg["region"], cfg["relevance_language"]):
            if video_id not in seen:
                seen.add(video_id)
                video_ids.append(video_id)

    ideas = _fetch_video_stats(video_ids)
    ideas.sort(key=lambda i: i["views"], reverse=True)
    return ideas[:MAX_IDEAS]


def refresh_ideas(language: str = DEFAULT_LANGUAGE) -> bool:
    """Одноразово оновлює кеш ідей для однієї мови. Повертає True, якщо
    оновлення вдалося."""
    language = _normalize_language(language)

    if not YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY не задано; трендові ідеї недоступні")
        return False

    try:
        ideas = _fetch_niche_trending(language)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        logger.warning("YouTube API недоступний (%s), лишаємо попередній список ідей", exc)
        return False

    if not ideas:
        return False

    with _cache_lock:
        _cached_ideas[language] = ideas
        _last_updated[language] = time.time()
    return True


def get_ideas(language: str = DEFAULT_LANGUAGE) -> dict:
    language = _normalize_language(language)
    with _cache_lock:
        return {
            "ideas": list(_cached_ideas[language]),
            "last_updated": _last_updated[language],
            "source": "youtube",
            "error": None if YOUTUBE_API_KEY else "Не задано YOUTUBE_API_KEY.",
        }


def _background_refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        for language in LANGUAGES:
            refresh_ideas(language)


def start_background_refresh():
    """Одразу підтягує актуальний список ДЛЯ ОБОХ мов (це і є "оновлення
    при заході на сторінку" - сервер підхоплює свіжі тренди одразу при
    старті) і запускає фоновий потік, який періодично оновлює обидві
    мови (раз на REFRESH_INTERVAL_SECONDS). Після цього - лише вручну
    кнопкою "Оновити"."""
    for language in LANGUAGES:
        refresh_ideas(language)
    thread = threading.Thread(target=_background_refresh_loop, daemon=True)
    thread.start()

