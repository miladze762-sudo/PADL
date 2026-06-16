from __future__ import annotations

from .models import BookingResult, PendingBooking, Profile, SearchPreferences, SlotCandidate
from .selection import format_phone_for_site


class BookingError(RuntimeError):
    pass


def _error_text(error: BaseException) -> str:
    return str(error).lower()


def _classify_hold_error(error: BaseException) -> BookingError:
    text = _error_text(error)
    if "409" in text or "conflict" in text:
        return BookingError("Слот уже недоступен")
    if "400" in text or "404" in text or "expired" in text:
        return BookingError("Сессия бронирования истекла")
    return BookingError("Не удалось удержать слот")


class BookingCoordinator:
    def __init__(self, api):
        self.api = api

    async def _send_sms(self, *, session_id: str, hold_id: str, profile: Profile) -> None:
        site_phone = format_phone_for_site(profile.phone)
        response = await self.api.send_sms(session_id=session_id, hold_id=hold_id, phone=site_phone)
        status = response.get("status") or response.get("message") or "accepted"
        print(
            f"SMS request accepted: session_id={session_id} hold_id={hold_id} status={status}",
            flush=True,
        )

    async def reserve_slot(
        self,
        slot: SlotCandidate,
        profile: Profile,
        preferences: SearchPreferences,
    ) -> PendingBooking:
        session = await self.api.create_session(
            event_type=preferences.event_type,
            court_id=slot.court_id,
            date=slot.date_key,
        )
        session_id = str(session["session_id"])
        try:
            hold = await self.api.hold_slot(
                session_id,
                event_id=slot.event_id,
                starts_at=slot.starts_at.isoformat(),
                duration_minutes=slot.duration_minutes,
                tickets_count=preferences.tickets_count,
            )
        except Exception as exc:
            raise _classify_hold_error(exc) from exc

        hold_id = str(hold["hold_id"])
        await self._send_sms(session_id=session_id, hold_id=hold_id, profile=profile)
        return PendingBooking(
            session_id=session_id,
            hold_id=hold_id,
            slot=slot,
            tickets_count=preferences.tickets_count,
            expires_at=hold.get("expires_at") or session.get("expires_at"),
        )

    async def resend_sms(self, pending: PendingBooking, profile: Profile) -> None:
        await self._send_sms(
            session_id=pending.session_id,
            hold_id=pending.hold_id,
            profile=profile,
        )

    async def sms_status(self, pending: PendingBooking, profile: Profile) -> dict:
        site_phone = format_phone_for_site(profile.phone)
        return await self.api.sms_status(
            session_id=pending.session_id,
            hold_id=pending.hold_id,
            phone=site_phone,
        )

    async def confirm_with_sms(
        self,
        pending: PendingBooking,
        profile: Profile,
        code: str,
    ) -> BookingResult:
        if pending.result:
            return pending.result

        try:
            site_phone = format_phone_for_site(profile.phone)
            await self.api.verify_sms(
                session_id=pending.session_id,
                hold_id=pending.hold_id,
                phone=site_phone,
                code=code,
            )
        except Exception as exc:
            text = _error_text(exc)
            if "400" in text or "invalid" in text or "bad request" in text:
                raise BookingError("Неверный СМС-код") from exc
            raise BookingError("Не удалось проверить СМС-код") from exc

        try:
            response = await self.api.confirm_booking(
                session_id=pending.session_id,
                hold_id=pending.hold_id,
                first_name=profile.first_name,
                last_name=profile.last_name,
                email=profile.email,
                phone=site_phone,
            )
        except Exception as exc:
            raise BookingError("Не удалось подтвердить бронь") from exc

        result = BookingResult(
            booking_id=str(response.get("booking_id", "")),
            slot=pending.slot,
            tickets_count=pending.tickets_count,
        )
        pending.result = result
        return result
