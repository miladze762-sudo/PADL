from __future__ import annotations

import re
from collections.abc import Iterable

from .models import DEFAULT_VENUE_IDS


KNOWN_VENUE_TITLES = {
    12: "Баррикадная",
    14: "Третьяковская",
    15: "Римская",
}


class VenueSelectionError(ValueError):
    pass


def parse_venue_ids(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower()
    if normalized == "all":
        return DEFAULT_VENUE_IDS

    raw_items = [item for item in re.split(r"[,\s]+", normalized) if item]
    if not raw_items:
        raise VenueSelectionError("Формат: /venues 12,14")

    venue_ids: list[int] = []
    for raw_item in raw_items:
        try:
            venue_id = int(raw_item)
        except ValueError as exc:
            raise VenueSelectionError(
                f"Площадка должна быть числом: {raw_item}. Доступны: {available_venue_ids_label()}."
            ) from exc
        if venue_id not in KNOWN_VENUE_TITLES:
            raise VenueSelectionError(
                f"Неизвестная площадка: {venue_id}. Доступны: {available_venue_ids_label()}."
            )
        if venue_id not in venue_ids:
            venue_ids.append(venue_id)

    return tuple(venue_ids)


def venue_selection_label(venue_ids: Iterable[int]) -> str:
    selected = tuple(venue_ids)
    if selected == DEFAULT_VENUE_IDS:
        return "все площадки"
    return ", ".join(KNOWN_VENUE_TITLES.get(venue_id, str(venue_id)) for venue_id in selected)


def current_venues_message(venue_ids: Iterable[int]) -> str:
    return (
        f"Текущие площадки: {venue_selection_label(venue_ids)}.\n\n"
        "Изменить: /venues 12,14\n"
        "Все площадки: /venues all\n"
        "Доступные площадки:\n"
        f"{available_venues_text()}"
    )


def venues_saved_message(venue_ids: Iterable[int]) -> str:
    return f"Площадки сохранены: {venue_selection_label(venue_ids)}."


def available_venues_text() -> str:
    return "\n".join(
        f"{venue_id} - {title}" for venue_id, title in KNOWN_VENUE_TITLES.items()
    )


def available_venue_ids_label() -> str:
    return ", ".join(str(venue_id) for venue_id in KNOWN_VENUE_TITLES)
