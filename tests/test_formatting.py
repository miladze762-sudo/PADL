import unittest

from padlbot.models import BookingResult, PendingBooking, SlotCandidate
from padlbot.formatting import (
    format_booking_result,
    format_monitoring_slot_messages,
    format_pending,
)


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
        self.assertIn("Найдены свободные слоты PADL", joined)
        self.assertIn("https://outdoor.sport.mos.ru/#venues-events", joined)
        self.assertIn("Площадка: Римская", joined)
        for index in range(8):
            self.assertIn(f"Корт: Корт {index}", joined)

    def test_pending_booking_message_is_russian(self):
        message = format_pending(
            PendingBooking(
                session_id="session-1",
                hold_id="hold-1",
                slot=make_slot(1),
                tickets_count=2,
            )
        )

        self.assertIn("Слот удержан. Жду СМС-код.", message)
        self.assertIn("Корт: Корт 1", message)

    def test_booking_result_message_is_russian(self):
        message = format_booking_result(
            BookingResult(
                booking_id="777",
                slot=make_slot(2),
                tickets_count=2,
            )
        )

        self.assertIn("Бронь подтверждена!", message)
        self.assertIn("Номер брони: #777", message)
        self.assertIn("отправьте /search", message)
        self.assertNotIn("17:00-22:00", message)


if __name__ == "__main__":
    unittest.main()
