"""
Модуль трендових ідей для відео.

У фоновому потоці періодично підтягує список найпопулярніших відео з
YouTube Data API v3 (chart=mostPopular) і зберігає його в пам'яті,
відсортованим від найпопулярнішого до найменш популярного за кількістю
переглядів. Назви цих відео пропонуються користувачу на сайті як
готові ідеї теми - досить клікнути, і тема підставиться у форму.

Якщо YOUTUBE_API_KEY не задано (або запит не вдався), повертається
невеликий локальний DEMO-список ідей - так само, як інші модулі
конвеєра, ця частина ніколи не "падає" через відсутність чи збій
зовнішнього сервісу.
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
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_TIMEOUT_SECONDS = 20

REGION_CODE = "UA"
MAX_RESULTS = 25
REFRESH_INTERVAL_SECONDS = 30 * 60  # оновлювати список раз на 30 хвилин

# Резервний список ідей, якщо YOUTUBE_API_KEY не задано або запит не вдався
DEMO_IDEAS = [
    {"title": "Що буде, якщо Земля перестане обертатися?", "views": None, "thumbnail": None},
    {"title": "Найдивовижніші факти про космос", "views": None, "thumbnail": None},
    {"title": "Що станеться, якщо зникнуть усі бджоли?", "views": None, "thumbnail": None},
    {"title": "5 речей, які можуть знищити людство", "views": None, "thumbnail": None},
    {"title": "Що буде, якщо викопати тунель крізь Землю?", "views": None, "thumbnail": None},
]

_cache_lock = threading.Lock()
_cached_ideas = list(DEMO_IDEAS)
_last_updated = None


def _fetch_trending_videos() -> list:
    """Один запит до YouTube Data API за найпопулярнішими відео регіону."""
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": REGION_CODE,
        "maxResults": str(MAX_RESULTS),
        "key": YOUTUBE_API_KEY,
    }
    url = f"{YOUTUBE_API_URL}?{urllib.parse.urlencode(params)}"
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

    # mostPopular і так відсортований YouTube'ом, але сортуємо явно -
    # це саме те, що просив користувач ("від найбільш до найменш популярного")
    ideas.sort(key=lambda i: i["views"], reverse=True)
    return ideas


def refresh_ideas() -> bool:
    """Одноразово оновлює кеш ідей. Повертає True, якщо оновлення вдалося."""
    global _cached_ideas, _last_updated

    if not YOUTUBE_API_KEY:
        return False

    try:
        ideas = _fetch_trending_videos()
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
