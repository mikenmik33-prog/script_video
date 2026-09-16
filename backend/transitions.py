"""
Бібліотека промтів переходів між сценами.

Кожен запис - готова текстова підказка, яку користувач читає при
монтажі (CapCut, Premiere тощо) і сама вручну накладає ефект - жодного
автоматичного FFmpeg-монтажу застосунок не робить.

Google Gemini (ai.py, _build_script_prompt) для КОЖНОЇ сцени сам обирає один
ключ із SCENE_TRANSITIONS, що найкраще передає, як саме ЦЯ сцена має
перетекти в НАСТУПНУ (а не просто по черзі підряд) - враховує зміст
обох сцен: чи продовжується та сама дія/предмет, чи різко міняється
тема, чи потрібен спокійний плавний перехід, чи навпаки різкий/
енергійний.
"""

SCENE_TRANSITIONS = {
    "hard_cut": (
        "Hard cut: instant jump to the next clip, no transition effect at "
        "all. Best when the next scene keeps the same energy and pace and "
        "simply continues with a new fact or beat right away."
    ),
    "match_action_cut": (
        "Match cut: cut on matching motion, shape or subject so the last "
        "frame of this scene visually flows into the first frame of the "
        "next. Best when the same subject, object or movement carries over "
        "directly into the next scene."
    ),
    "cross_dissolve": (
        "Cross-dissolve: the two scenes smoothly blend into one another "
        "over about half a second. Best for a shift in mood, tone or time "
        "period, or before a slower, more reflective moment."
    ),
    "whip_pan_transition": (
        "Whip-pan transition: a fast motion-blur swipe wipes this scene "
        "away into the next. Best for high-energy, urgent moments or a "
        "sudden dramatic reveal."
    ),
    "zoom_punch_transition": (
        "Zoom punch: a quick snap-zoom into a detail of this scene punches "
        "through into the next scene. Best right before revealing a "
        "shocking or surprising detail."
    ),
    "slide_wipe": (
        "Slide wipe: the next scene slides in and pushes this one off "
        "screen. Best for a sequence of related items, a list, or a "
        "comparison between this scene and the next."
    ),
    "flash_cut": (
        "Flash cut: a brief white flash bridges into the next scene. Best "
        "for a big reveal, a punchline, or a strong emotional beat."
    ),
    "fade_to_black": (
        "Fade to black, then fade in on the next scene. Reserve this for "
        "the very end of the video - a closing beat after the final line, "
        "not between two ordinary scenes."
    ),
}

DEFAULT_TRANSITION = "hard_cut"
