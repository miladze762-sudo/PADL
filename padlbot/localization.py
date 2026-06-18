from __future__ import annotations

import re


VENUE_TITLE_TRANSLATIONS = {
    "Barrikadnaya": "Баррикадная",
    "Tretyakovskaya": "Третьяковская",
    "Rimskaya": "Римская",
}

PADL_BOOKING_URL = "https://outdoor.sport.mos.ru/#venues-events"


def start_help_message() -> str:
    return (
        "Бот PADL готов.\n\n"
        "Запустить постоянный мониторинг: /search\n"
        "Бот ищет без ограничения по времени.\n"
        "Записывайтесь вручную на сайте PADL:\n"
        f"{PADL_BOOKING_URL}\n"
        "Другие команды: /now, /status, /stop"
    )


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
