import unittest

from padlbot.booking import BookingCoordinator, BookingError
from padlbot.models import Profile, SearchPreferences, SlotCandidate


class FakeOutdoorApi:
    def __init__(self):
        self.created_sessions = []
        self.hold_payloads = []
        self.sent_sms = []
        self.sms_status_checks = []
        self.verified_codes = []
        self.confirm_payloads = []
        self.hold_error = None
        self.verify_error = None
        self.confirm_error = None

    async def create_session(self, *, event_type, court_id, date):
        self.created_sessions.append(
            {"event_type": event_type, "court_id": court_id, "date": date}
        )
        return {"session_id": "session-1", "expires_at": "2026-06-09T20:00:00+03:00"}

    async def hold_slot(self, session_id, *, event_id, starts_at, duration_minutes, tickets_count):
        if self.hold_error:
            raise self.hold_error
        self.hold_payloads.append(
            {
                "session_id": session_id,
                "event_id": event_id,
                "starts_at": starts_at,
                "duration_minutes": duration_minutes,
                "tickets_count": tickets_count,
            }
        )
        return {"hold_id": "hold-1", "expires_at": "2026-06-09T20:00:00+03:00"}

    async def send_sms(self, *, session_id, hold_id, phone):
        self.sent_sms.append({"session_id": session_id, "hold_id": hold_id, "phone": phone})
        return {"status": "sent"}

    async def sms_status(self, *, session_id, hold_id, phone):
        self.sms_status_checks.append(
            {"session_id": session_id, "hold_id": hold_id, "phone": phone}
        )
        return {"status": "pending", "retry_after_seconds": 0}

    async def verify_sms(self, *, session_id, hold_id, phone, code):
        if self.verify_error:
            raise self.verify_error
        self.verified_codes.append(
            {"session_id": session_id, "hold_id": hold_id, "phone": phone, "code": code}
        )
        return {"status": "verified"}

    async def confirm_booking(
        self,
        *,
        session_id,
        hold_id,
        first_name,
        last_name,
        email,
        phone,
    ):
        if self.confirm_error:
            raise self.confirm_error
        self.confirm_payloads.append(
            {
                "session_id": session_id,
                "hold_id": hold_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
            }
        )
        return {"booking_id": 777}


class BookingCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = FakeOutdoorApi()
        self.profile = Profile(
            chat_id=100,
            first_name="Ivan",
            last_name="Ivanov",
            phone="+79161234567",
            email="ivan@example.com",
        )
        self.preferences = SearchPreferences(tickets_count=2)
        self.slot = SlotCandidate(
            venue_id=12,
            venue_title="Barrikadnaya",
            court_id=10,
            court_title="Court 1",
            date_key="2026-06-12",
            event_id=945,
            starts_at="2026-06-12T17:00:00.000+03:00",
            ends_at="2026-06-12T19:00:00.000+03:00",
            duration_minutes=120,
            available_tickets=3,
        )

    async def test_successful_booking_holds_slot_sends_sms_and_confirms_after_code(self):
        coordinator = BookingCoordinator(self.api)

        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)
        result = await coordinator.confirm_with_sms(pending, self.profile, "4821")

        self.assertEqual(self.api.created_sessions[0]["event_type"], "free_play")
        self.assertEqual(
            self.api.hold_payloads[0],
            {
                "session_id": "session-1",
                "event_id": 945,
                "starts_at": "2026-06-12T17:00:00+03:00",
                "duration_minutes": 120,
                "tickets_count": 2,
            },
        )
        self.assertEqual(self.api.sent_sms[0]["phone"], "+79161234567")
        self.assertEqual(self.api.verified_codes[0]["code"], "4821")
        self.assertEqual(self.api.verified_codes[0]["phone"], "+79161234567")
        self.assertEqual(self.api.confirm_payloads[0]["phone"], "+79161234567")
        self.assertEqual(self.api.confirm_payloads[0]["email"], "ivan@example.com")
        self.assertEqual(result.booking_id, "777")
        self.assertEqual(result.slot.event_id, 945)

    async def test_duplicate_sms_code_after_success_does_not_confirm_twice(self):
        coordinator = BookingCoordinator(self.api)
        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

        first = await coordinator.confirm_with_sms(pending, self.profile, "4821")
        second = await coordinator.confirm_with_sms(pending, self.profile, "4821")

        self.assertEqual(first.booking_id, "777")
        self.assertEqual(second.booking_id, "777")
        self.assertEqual(len(self.api.verified_codes), 1)
        self.assertEqual(len(self.api.confirm_payloads), 1)

    async def test_resend_sms_code_uses_site_phone_format(self):
        coordinator = BookingCoordinator(self.api)
        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

        await coordinator.resend_sms(pending, self.profile)

        self.assertEqual(len(self.api.sent_sms), 2)
        self.assertEqual(self.api.sent_sms[1]["phone"], "+79161234567")

    async def test_sms_status_uses_site_phone_format(self):
        coordinator = BookingCoordinator(self.api)
        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

        status = await coordinator.sms_status(pending, self.profile)

        self.assertEqual(status["status"], "pending")
        self.assertEqual(self.api.sms_status_checks[0]["phone"], "+79161234567")

    async def test_slot_disappeared_during_hold_raises_booking_error(self):
        coordinator = BookingCoordinator(self.api)
        self.api.hold_error = RuntimeError("409 Conflict")

        with self.assertRaisesRegex(BookingError, "Слот уже недоступен"):
            await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

    async def test_expired_session_during_hold_raises_booking_error(self):
        coordinator = BookingCoordinator(self.api)
        self.api.hold_error = RuntimeError("404 Not Found")

        with self.assertRaisesRegex(BookingError, "Сессия бронирования истекла"):
            await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

    async def test_bad_sms_code_raises_booking_error(self):
        coordinator = BookingCoordinator(self.api)
        self.api.verify_error = RuntimeError("400 Bad Request")
        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

        with self.assertRaisesRegex(BookingError, "Неверный СМС-код"):
            await coordinator.confirm_with_sms(pending, self.profile, "1111")

    async def test_confirm_failure_raises_booking_error(self):
        coordinator = BookingCoordinator(self.api)
        self.api.confirm_error = RuntimeError("500 Server Error")
        pending = await coordinator.reserve_slot(self.slot, self.profile, self.preferences)

        with self.assertRaisesRegex(BookingError, "Не удалось подтвердить бронь"):
            await coordinator.confirm_with_sms(pending, self.profile, "4821")


if __name__ == "__main__":
    unittest.main()
