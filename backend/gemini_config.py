"""Shared Gemini configuration and lightweight task-based model routing."""

import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT_SECONDS = 60

# Keep GEMINI_MODEL as a backwards-compatible override for existing Render
# environments. New deployments can tune each workload independently.
GEMINI_SCRIPT_MODEL = os.getenv(
    "GEMINI_SCRIPT_MODEL",
    os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
).strip()
GEMINI_IDEA_MODEL = os.getenv(
    "GEMINI_IDEA_MODEL",
    "gemini-3.5-flash-lite",
).strip()
GEMINI_COMPLEX_MODEL = os.getenv("GEMINI_COMPLEX_MODEL", "").strip()


def model_for_script(topic: str) -> str:
    """Use the optional stronger model only for clearly complex topics."""
    if GEMINI_COMPLEX_MODEL:
        text = topic.lower()
        complex_markers = (
            "compare", "comparison", "timeline", "investigation",
            "multiple people", "how did", "чому", "порівняй",
            "розслідування", "хронологія",
        )
        if len(topic) > 180 or any(marker in text for marker in complex_markers):
            return GEMINI_COMPLEX_MODEL
    return GEMINI_SCRIPT_MODEL
