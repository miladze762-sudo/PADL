from __future__ import annotations

import re


VENUE_TITLE_TRANSLATIONS = {
    "Barrikadnaya": "Баррикадная",
    "Tretyakovskaya": "Третьяковская",
    "Rimskaya": "Римская",
}


def localize_venue_title(title: str) -> str:
    normalized = title.strip()
    return VENUE_TITLE_TRANSLATIONS.get(normalized, normalized)


def localize_court_title(title: str) -> str:
    normalized = title.strip()
    match = re.fullmatch(r"court\s+(.+)", normalized, flags=re.IGNORECASE)
    if match:
        return f"Корт {match.group(1)}"
    return normalized


def event_type_label(event_type: str) -> str:
    if event_type == "free_play":
        return "свободная игра"
    return event_type
