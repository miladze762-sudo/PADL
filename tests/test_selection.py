import unittest

from padlbot.models import SearchPreferences, SlotCandidate
from padlbot.selection import (
    choose_best_slot,
    extract_candidates,
    extract_sms_code,
    format_phone_for_site,
    normalize_phone,
)


class SelectionTests(unittest.TestCase):
    def test_extract_candidates_respects_window_ticket_count_and_durations(self):
        preferences = SearchPreferences(
            start_time="17:00",
            end_time="22:00",
            tickets_count=2,
            durations=(120, 90, 60),
            venue_ids=(12, 14, 15),
        )
        availability = {
            "events": [
                {
                    "id": 900,
                    "starts": [
                        {
                            "time": "16:30",
                            "starts_at": "2026-06-12T16:30:00.000+03:00",
                            "durations": {
                                "60": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 4,
                                    "starts_at": "2026-06-12T16:30:00.000+03:00",
                                    "ends_at": "2026-06-12T17:30:00.000+03:00",
                                }
                            },
                        }
                    ],
                },
                {
                    "id": 945,
                    "starts": [
                        {
                            "time": "17:00",
                            "starts_at": "2026-06-12T17:00:00.000+03:00",
                            "durations": {
                                "30": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 4,
                                    "starts_at": "2026-06-12T17:00:00.000+03:00",
                                    "ends_at": "2026-06-12T17:30:00.000+03:00",
                                },
                                "60": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 2,
                                    "starts_at": "2026-06-12T17:00:00.000+03:00",
                                    "ends_at": "2026-06-12T18:00:00.000+03:00",
                                },
                            },
                        }
                    ],
                },
                {
                    "id": 946,
                    "starts": [
                        {
                            "time": "20:30",
                            "starts_at": "2026-06-12T20:30:00.000+03:00",
                            "durations": {
                                "120": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 4,
                                    "starts_at": "2026-06-12T20:30:00.000+03:00",
                                    "ends_at": "2026-06-12T22:30:00.000+03:00",
                                }
                            },
                        },
                        {
                            "time": "21:00",
                            "starts_at": "2026-06-12T21:00:00.000+03:00",
                            "durations": {
                                "60": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 1,
                                    "starts_at": "2026-06-12T21:00:00.000+03:00",
                                    "ends_at": "2026-06-12T22:00:00.000+03:00",
                                }
                            },
                        },
                        {
                            "time": "21:00",
                            "starts_at": "2026-06-12T21:00:00.000+03:00",
                            "durations": {
                                "60": {
                                    "enabled": True,
                                    "booking_open": True,
                                    "available_tickets": 2,
                                    "starts_at": "2026-06-12T21:00:00.000+03:00",
                                    "ends_at": "2026-06-12T22:00:00.000+03:00",
                                }
                            },
                        },
                    ],
                },
            ]
        }

        candidates = extract_candidates(
            availability=availability,
            venue_id=12,
            venue_title="Barrikadnaya",
            court_id=10,
            court_title="Court 1",
            date_key="2026-06-12",
            preferences=preferences,
        )

        self.assertEqual(
            [(slot.event_id, slot.starts_at.isoformat(), slot.duration_minutes) for slot in candidates],
            [
                (945, "2026-06-12T17:00:00+03:00", 60),
                (946, "2026-06-12T21:00:00+03:00", 60),
            ],
        )

    def test_choose_best_slot_uses_earliest_time_then_venue_order_then_duration(self):
        slots = [
            SlotCandidate(
                venue_id=15,
                venue_title="Rimskaya",
                court_id=31,
                court_title="Court 1",
                date_key="2026-06-12",
                event_id=1,
                starts_at="2026-06-12T17:30:00.000+03:00",
                ends_at="2026-06-12T19:30:00.000+03:00",
                duration_minutes=120,
                available_tickets=4,
            ),
            SlotCandidate(
                venue_id=12,
                venue_title="Barrikadnaya",
                court_id=10,
                court_title="Court 1",
                date_key="2026-06-12",
                event_id=2,
                starts_at="2026-06-12T17:30:00.000+03:00",
                ends_at="2026-06-12T18:30:00.000+03:00",
                duration_minutes=60,
                available_tickets=4,
            ),
            SlotCandidate(
                venue_id=12,
                venue_title="Barrikadnaya",
                court_id=10,
                court_title="Court 1",
                date_key="2026-06-12",
                event_id=3,
                starts_at="2026-06-12T17:30:00.000+03:00",
                ends_at="2026-06-12T19:30:00.000+03:00",
                duration_minutes=120,
                available_tickets=4,
            ),
            SlotCandidate(
                venue_id=14,
                venue_title="Tretyakovskaya",
                court_id=20,
                court_title="Court 1",
                date_key="2026-06-12",
                event_id=4,
                starts_at="2026-06-12T18:00:00.000+03:00",
                ends_at="2026-06-12T20:00:00.000+03:00",
                duration_minutes=120,
                available_tickets=4,
            ),
        ]
        preferences = SearchPreferences(venue_ids=(12, 14, 15), durations=(120, 90, 60))

        best = choose_best_slot(slots, preferences)

        self.assertIsNotNone(best)
        self.assertEqual(best.event_id, 3)

    def test_extract_candidates_respects_optional_target_dates(self):
        preferences = SearchPreferences(target_dates=("2026-06-13",))
        availability = {
            "events": [
                {
                    "id": 945,
                    "starts": [
                        {
                            "time": "17:00",
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
        }

        candidates = extract_candidates(
            availability=availability,
            venue_id=12,
            venue_title="Barrikadnaya",
            court_id=10,
            court_title="Court 1",
            date_key="2026-06-12",
            preferences=preferences,
        )

        self.assertEqual(candidates, [])

    def test_extract_sms_code_returns_only_isolated_four_digit_code(self):
        self.assertEqual(extract_sms_code("Kod podtverzhdeniya: 4821"), "4821")
        self.assertEqual(extract_sms_code("PADL code 0007. Nikomu ne soobshchayte."), "0007")
        self.assertIsNone(extract_sms_code("booking id 12345"))
        self.assertIsNone(extract_sms_code("no digits here"))

    def test_normalize_phone_returns_russian_e164(self):
        self.assertEqual(normalize_phone("+7 (916) 123-45-67"), "+79161234567")
        self.assertEqual(normalize_phone("8 916 123 45 67"), "+79161234567")
        self.assertIsNone(normalize_phone("12345"))

    def test_format_phone_for_site_matches_site_normalized_phone(self):
        self.assertEqual(format_phone_for_site("+7 (916) 123-45-67"), "+79161234567")
        self.assertEqual(format_phone_for_site("8 960 748 05 65"), "+79607480565")


if __name__ == "__main__":
    unittest.main()
