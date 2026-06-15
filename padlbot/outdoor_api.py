from __future__ import annotations

from types import TracebackType
from typing import Any, Optional, Type

try:
    import aiohttp
except ImportError:  # pragma: no cover - exercised only before dependencies are installed.
    aiohttp = None


class OutdoorApiError(RuntimeError):
    pass


class OutdoorApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0):
        if aiohttp is None:
            raise OutdoorApiError("aiohttp is not installed. Run: pip install -r requirements.txt")
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.client: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "OutdoorApiClient":
        self.client = aiohttp.ClientSession(
            timeout=self.timeout,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://outdoor.sport.mos.ru",
                "Referer": "https://outdoor.sport.mos.ru/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
        )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    async def venues(self) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/items/venues",
            params={
                "filter[status][_eq]": "published",
                "sort": "sort",
                "fields": "id,title,address,working_hours,sort,status",
            },
        )

    async def date_options(self, *, event_type: str, venue_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/booking/date-options",
            params={"event_type": event_type, "venue_id": venue_id},
        )

    async def availability(
        self,
        *,
        event_type: str,
        venue_id: int,
        court_id: int,
        date: str,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/booking/availability",
            params={
                "event_type": event_type,
                "venue_id": venue_id,
                "court_id": court_id,
                "date": date,
            },
        )

    async def create_session(self, *, event_type: str, court_id: int, date: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/booking/session",
            json={"event_type": event_type, "court_id": court_id, "date": date},
        )

    async def hold_slot(
        self,
        session_id: str,
        *,
        event_id: int,
        starts_at: str,
        duration_minutes: int,
        tickets_count: int,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/booking/session/{session_id}/hold",
            json={
                "event_id": event_id,
                "starts_at": starts_at,
                "duration_minutes": duration_minutes,
                "tickets_count": tickets_count,
            },
        )

    async def send_sms(self, *, session_id: str, hold_id: str, phone: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/booking/sms/send",
            json={"session_id": session_id, "hold_id": hold_id, "phone": phone},
        )

    async def sms_status(self, *, session_id: str, hold_id: str, phone: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/booking/sms/status",
            params={"session_id": session_id, "hold_id": hold_id, "phone": phone},
        )

    async def verify_sms(
        self,
        *,
        session_id: str,
        hold_id: str,
        phone: str,
        code: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/booking/sms/verify",
            json={
                "session_id": session_id,
                "hold_id": hold_id,
                "phone": phone,
                "code": code,
            },
        )

    async def confirm_booking(
        self,
        *,
        session_id: str,
        hold_id: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/booking/confirm",
            json={
                "session_id": session_id,
                "hold_id": hold_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "privacy_policy_accepted": True,
                "personal_data_accepted": True,
            },
        )

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        if self.client is None:
            raise OutdoorApiError("OutdoorApiClient must be used as an async context manager")
        async with self.client.request(method, self.base_url + path, **kwargs) as response:
            text = await response.text()
            if response.status >= 400:
                raise OutdoorApiError(f"{response.status} {text}")
            try:
                return await response.json()
            except Exception as exc:
                raise OutdoorApiError(f"Invalid JSON response from {path}") from exc
