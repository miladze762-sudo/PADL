from __future__ import annotations

from .localization import localize_court_title, localize_venue_title
from .models import SearchPreferences, SlotCandidate
from .selection import choose_best_slot, extract_candidates_from_available_events, sort_slots
from .venues import KNOWN_VENUE_TITLES


class SlotScanner:
    def __init__(self, api):
        self.api = api

    async def find_best_slot(self, preferences: SearchPreferences) -> SlotCandidate | None:
        return choose_best_slot(await self.find_slots(preferences), preferences)

    async def find_slots(self, preferences: SearchPreferences) -> list[SlotCandidate]:
        venue_titles = await self._venue_titles()
        all_candidates: list[SlotCandidate] = []
        for venue_id in preferences.venue_ids:
            options = await self.api.date_options(
                event_type=preferences.event_type,
                venue_id=venue_id,
            )
            for court in options.get("courts", []):
                court_id = int(court.get("court_id") or 0)
                if court_id <= 0 or not court.get("has_bookable_slots"):
                    continue
                court_title = localize_court_title(
                    str(court.get("court_title") or f"Court {court_id}")
                )
                all_candidates.extend(
                    extract_candidates_from_available_events(
                        available_events=court.get("available_events") or [],
                        venue_id=venue_id,
                        venue_title=venue_titles.get(
                            venue_id,
                            KNOWN_VENUE_TITLES.get(venue_id, str(venue_id)),
                        ),
                        court_id=court_id,
                        court_title=court_title,
                        preferences=preferences,
                    )
                )
        return sort_slots(all_candidates, preferences)

    async def _venue_titles(self) -> dict[int, str]:
        try:
            response = await self.api.venues()
        except Exception:
            return KNOWN_VENUE_TITLES.copy()
        titles: dict[int, str] = KNOWN_VENUE_TITLES.copy()
        for venue in response.get("data", []):
            try:
                venue_id = int(venue.get("id"))
            except (TypeError, ValueError):
                continue
            title = str(venue.get("title") or "").strip()
            if title:
                titles[venue_id] = localize_venue_title(title)
        return titles
