import unittest

from padlbot.models import SlotCandidate
from padlbot.formatting import format_monitoring_slot_messages


def make_slot(index: int) -> SlotCandidate:
    return SlotCandidate(
        venue_id=15,
        venue_title="Rimskaya",
        court_id=20 + index,
        court_title=f"Court {index}",
        date_key="2026-06-16",
        event_id=1000 + index,
        starts_at=f"2026-06-16T{10 + index:02d}:00:00.000+03:00",
        ends_at=f"2026-06-16T{11 + index:02d}:00:00.000+03:00",
        duration_minutes=60,
        available_tickets=2,
    )


class FormattingTests(unittest.TestCase):
    def test_monitoring_slot_messages_split_under_limit_and_keep_all_slots(self):
        slots = [make_slot(index) for index in range(8)]

        messages = format_monitoring_slot_messages(
            slots,
            tickets_count=2,
            max_message_length=260,
        )

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 260 for message in messages))
        joined = "\n".join(messages)
        for index in range(8):
            self.assertIn(f"Court: Court {index}", joined)


if __name__ == "__main__":
    unittest.main()
