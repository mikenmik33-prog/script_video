"""
Модуль трендових ідей для відео.

Працюємо в одній фіксованій ніші - цікаві факти, наука/технології та
загадкові/містичні історії (у форматі оповіді про щось цікаве, а не
гейминг/меми/трейлери). Тому замість "просто найпопулярніші відео
YouTube" (chart=mostPopular) шукаємо трендові відео САМЕ в цій ніші
через пошук (search.list за ключовими словами NICHE_QUERIES), а тоді
підтягуємо реальну кількість переглядів (videos.list) і сортуємо від
найбільшої до найменшої.

Це коштує значно дорожчої квоти YouTube API, ніж chart=mostPopular
(search.list = 100 одиниць за виклик, безкоштовна квота - 10 000/добу),
тому фонове оновлення відбувається рідше (раз на кілька годин), а не
щохвилини.

Якщо YOUTUBE_API_KEY не задано (або запит не вдався), повертається
невеликий локальний DEMO-список ідей цієї ж ніші - так само, як інші
модулі конвеєра, ця частина ніколи не "падає" через відсутність чи
збій зовнішнього сервісу.
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

REGION_CODE = "UA"
RELEVANCE_LANGUAGE = "uk"

# Ніша: цікаві факти / наука і технології / загадкові історії - усе у
# форматі короткої розповіді "про щось цікаве"
NICHE_QUERIES = ["цікаві факти", "наукові факти", "загадкові історії факти"]
RESULTS_PER_QUERY = 10
MAX_IDEAS = 20

# search.list коштує 100 одиниць квоти за запит (у нас 3 запити на
# оновлення + 1 дешевий videos.list) - тому оновлюємо нечасто, щоб не
# вичерпати безкоштовну добову квоту (10 000 одиниць/добу)
REFRESH_INTERVAL_SECONDS = 3 * 60 * 60  # раз на 3 години

# Резервний список ідей тієї самої ніші, якщо YOUTUBE_API_KEY не задано
# або запит не вдався
DEMO_IDEAS = [
    {"title": "Що буде, якщо Земля перестане обертатися?", "views": None, "thumbnail": None},
    {"title": "Найдивовижніші факти про космос", "views": None, "thumbnail": None},
    {"title": "Що станеться, якщо зникнуть усі бджоли?", "views": None, "thumbnail": None},
    {"title": "Найзагадковіші історії, які досі не розкриті", "views": None, "thumbnail": None},
    {"title": "Що буде, якщо викопати тунель крізь Землю?", "views": None, "thumbnail": None},
]

_cache_lock = threading.Lock()
_cached_ideas = list(DEMO_IDEAS)
_last_updated = None


def _search_video_ids(query: str) -> list:
    """Пошук відео за ключовим словом ніші. Повертає список videoId
    (без статистики переглядів - search.list її не дає)."""
    params = {
        "part": "id",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "regionCode": REGION_CODE,
        "relevanceLanguage": RELEVANCE_LANGUAGE,
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


def _fetch_niche_trending() -> list:
    """Збирає трендові відео ніші з кількох пошукових запитів, прибирає
    дублікати і сортує від найбільшої кількості переглядів до найменшої."""
    video_ids = []
    seen = set()
    for query in NICHE_QUERIES:
        for video_id in _search_video_ids(query):
            if video_id not in seen:
                seen.add(video_id)
                video_ids.append(video_id)

    ideas = _fetch_video_stats(video_ids)
    ideas.sort(key=lambda i: i["views"], reverse=True)
    return ideas[:MAX_IDEAS]


def refresh_ideas() -> bool:
    """Одноразово оновлює кеш ідей. Повертає True, якщо оновлення вдалося."""
    global _cached_ideas, _last_updated

    if not YOUTUBE_API_KEY:
        return False

    try:
        ideas = _fetch_niche_trending()
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        logger.warning("YouTube API недоступний (%s), лишаємо попередній список ідей", exc)
        return False

    if not ideas:
        return False

    with _cache_lock:
        _cached_ideas = ideas
        _last_updated = time.time()
    return True


def get_ideas() -> dict:
    with _cache_lock:
        return {
            "ideas": list(_cached_ideas),
            "last_updated": _last_updated,
            "source": "youtube" if YOUTUBE_API_KEY else "demo",
        }


def _background_refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        refresh_ideas()


def start_background_refresh():
    """Одразу підтягує актуальний список і запускає фоновий потік, який
    періодично його оновлює (раз на REFRESH_INTERVAL_SECONDS)."""
    refresh_ideas()
    thread = threading.Thread(target=_background_refresh_loop, daemon=True)
    thread.start()
