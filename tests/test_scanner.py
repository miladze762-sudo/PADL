import unittest

from padlbot.models import SearchPreferences
from padlbot.scanner import SlotScanner


class FakeScannerApi:
    def __init__(self, *, date_options, availability):
        self._date_options = date_options
        self._availability = availability
        self.availability_calls = []

    async def venues(self):
        return {"data": [{"id": 12, "title": "Barrikadnaya"}]}

    async def date_options(self, *, event_type, venue_id):
        return self._date_options

    async def availability(self, *, event_type, venue_id, court_id, date):
        self.availability_calls.append(
            {
                "event_type": event_type,
                "venue_id": venue_id,
                "court_id": court_id,
                "date": date,
            }
        )
        return self._availability


class SlotScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_date_options_available_slots_instead_of_full_availability_grid(self):
        api = FakeScannerApi(
            date_options={
                "courts": [
                    {
                        "court_id": 10,
                        "court_title": "Court 1",
                        "has_bookable_slots": True,
                        "available_dates": ["2026-06-12"],
                        "available_events": [
                            {
                                "id": 945,
                                "event_date": "2026-06-12",
                                "available_slots": [
                                    {
                                        "starts_at": "2026-06-12T17:00:00.000+03:00",
                                        "ends_at": "2026-06-12T17:30:00.000+03:00",
                                        "duration_minutes": 30,
                                        "available_tickets": 4,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            availability={
                "events": [
                    {
                        "id": 945,
                        "starts": [
                            {
                                "starts_at": "2026-06-12T17:00:00.000+03:00",
                                "durations": {
                                    "60": {
                                        "enabled": True,
                                        "booking_open": True,
                                        "available_tickets": 2,
                                        "starts_at": "2026-06-12T17:00:00.000+03:00",
                                        "ends_at": "2026-06-12T18:00:00.000+03:00",
                                    }
                                },
                            }
                        ],
                    }
                ]
            },
        )

        slot = await SlotScanner(api).find_best_slot(
            SearchPreferences(venue_ids=(12,), durations=(120, 90, 60), tickets_count=2)
        )

        self.assertIsNone(slot)
        self.assertEqual(api.availability_calls, [])

    async def test_finds_matching_slot_from_date_options_available_slots(self):
        api = FakeScannerApi(
            date_options={
                "courts": [
                    {
                        "court_id": 10,
                        "court_title": "Court 1",
                        "has_bookable_slots": True,
                        "available_dates": ["2026-06-12"],
                        "available_events": [
                            {
                                "id": 945,
                                "event_date": "2026-06-12",
                                "available_slots": [
                                    {
                                        "starts_at": "2026-06-12T17:00:00.000+03:00",
                                        "ends_at": "2026-06-12T18:00:00.000+03:00",
                                        "duration_minutes": 60,
                                        "available_tickets": 2,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            availability={"events": []},
        )

        slot = await SlotScanner(api).find_best_slot(
            SearchPreferences(venue_ids=(12,), durations=(120, 90, 60), tickets_count=2)
        )

        self.assertIsNotNone(slot)
        self.assertEqual(slot.event_id, 945)
        self.assertEqual(slot.venue_title, "Баррикадная")
        self.assertEqual(slot.court_title, "Корт 1")
        self.assertEqual(slot.duration_minutes, 60)
        self.assertEqual(slot.available_tickets, 2)
        self.assertEqual(api.availability_calls, [])

    async def test_find_slots_returns_all_matching_available_slots_in_priority_order(self):
        api = FakeScannerApi(
            date_options={
                "courts": [
                    {
                        "court_id": 10,
                        "court_title": "Court 1",
                        "has_bookable_slots": True,
                        "available_events": [
                            {
                                "id": 945,
                                "available_slots": [
                                    {
                                        "starts_at": "2026-06-12T18:00:00.000+03:00",
                                        "ends_at": "2026-06-12T19:00:00.000+03:00",
                                        "duration_minutes": 60,
                                        "available_tickets": 2,
                                    },
                                    {
                                        "starts_at": "2026-06-12T17:00:00.000+03:00",
                                        "ends_at": "2026-06-12T18:00:00.000+03:00",
                                        "duration_minutes": 60,
                                        "available_tickets": 2,
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
            availability={"events": []},
        )

        slots = await SlotScanner(api).find_slots(
            SearchPreferences(venue_ids=(12,), durations=(120, 90, 60), tickets_count=2)
        )

        self.assertEqual([slot.starts_at.hour for slot in slots], [17, 18])


if __name__ == "__main__":
    unittest.main()
