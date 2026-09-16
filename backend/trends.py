"""Gemini-generated topic suggestions for the video generator.

Suggestions are adapted to the selected audience and language using the model's
knowledge only. The UI shows ten refreshable ideas; clicking one copies its
title into the topic field.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT_SECONDS = 60

DEFAULT_LANGUAGE = "en"
MAX_IDEAS = 10
REFRESH_INTERVAL_SECONDS = 6 * 60 * 60

LANGUAGES = {
    "en": {"language": "English", "audience": "adults in the United States"},
    "uk": {"language": "Ukrainian", "audience": "Ukrainian-speaking adults"},
}

_cache_lock = threading.Lock()
_cached_ideas = {lang: [] for lang in LANGUAGES}
_last_updated = {lang: None for lang in LANGUAGES}
_last_error = {lang: None for lang in LANGUAGES}


def _normalize_language(language: str) -> str:
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_gemini_text(body: dict) -> str:
    """Extract generated text from a Gemini generateContent response."""
    for candidate in body.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise RuntimeError("Gemini не повернув текстову відповідь для ідей.")


def _build_ideas_prompt(language: str) -> str:
    cfg = LANGUAGES[language]
    today = time.strftime("%Y-%m-%d")
    return f"""You are the topic editor for a short-form factual video channel.
Today is {today}. Create exactly {MAX_IDEAS} distinct topic ideas for
{cfg['audience']}. Write every title and hook in {cfg['language']}.

Focus on surprising facts, scientific discoveries, real human adventures, and
understandable current events. Prefer plausible, well-known facts and do not
invent details, fake discoveries, rumors, or unsupported numbers. Current events
are allowed only when they are clear and genuinely interesting to this audience.
Keep topics PG-13: no graphic violence, sexual content, hate,
political persuasion, or risky clickbait.

Return only a JSON object with an `ideas` array of exactly {MAX_IDEAS} items.
Each item must contain `title` (a short intriguing topic title) and `hook` (one
concise sentence explaining the surprising angle). Do not include URLs,
markdown, numbering, or extra fields."""


def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Не задано GEMINI_API_KEY.")

    schema = {
        "type": "object",
        "properties": {
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                    },
                    "required": ["title", "hook"],
                    "additionalProperties": False,
                },
                "minItems": MAX_IDEAS,
                "maxItems": MAX_IDEAS,
            }
        },
        "required": ["ideas"],
        "additionalProperties": False,
    }
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
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
        logger.warning("Gemini ideas API HTTP %s: %s", exc.code, details[:2000])
        raise
    return _extract_gemini_text(body)


def refresh_ideas(language: str = DEFAULT_LANGUAGE) -> bool:
    """Generate and cache ten ideas for one language."""
    language = _normalize_language(language)
    try:
        raw = _call_gemini(_build_ideas_prompt(language))
        data = json.loads(_strip_code_fence(raw))
        ideas = data.get("ideas") if isinstance(data, dict) else None
        if not isinstance(ideas, list) or len(ideas) != MAX_IDEAS:
            raise ValueError("Gemini повернув не рівно 10 ідей.")
        normalized = []
        for idea in ideas:
            if not isinstance(idea, dict) or not idea.get("title") or not idea.get("hook"):
                raise ValueError("Gemini повернув неповну ідею.")
            normalized.append({"title": str(idea["title"]).strip(), "hook": str(idea["hook"]).strip()})
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        logger.exception("Не вдалося оновити Gemini-ідеї")
        with _cache_lock:
            _last_error[language] = "Не вдалося оновити список ідей. Спробуйте ще раз."
        return False

    with _cache_lock:
        _cached_ideas[language] = normalized
        _last_updated[language] = time.time()
        _last_error[language] = None
    return True


def get_ideas(language: str = DEFAULT_LANGUAGE) -> dict:
    language = _normalize_language(language)
    with _cache_lock:
        return {
            "ideas": list(_cached_ideas[language]),
            "last_updated": _last_updated[language],
            "source": "gemini",
            "error": _last_error[language],
        }


def _background_refresh_loop():
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        for language in LANGUAGES:
            refresh_ideas(language)


def start_background_refresh():
    """Prepare both language lists at startup and refresh them periodically."""
    for language in LANGUAGES:
        refresh_ideas(language)
    threading.Thread(target=_background_refresh_loop, daemon=True).start()
