"""Real Google Calendar integration using Google's official Calendar API."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .base import Integration, IntegrationInfo
from .calendar import CalendarEvent
from .google_oauth import GoogleOAuth

CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)

class GoogleCalendarIntegration(Integration):
    info = IntegrationInfo("google_calendar", "Google Calendar read/create/update/delete integration", CALENDAR_SCOPES)

    def __init__(self, oauth: GoogleOAuth | None = None):
        self.oauth = oauth or GoogleOAuth(token_file=str(__import__("pathlib").Path.home()/".config"/"axon"/"calendar_token.json"))
        self._service = None

    def _api(self):
        if self._service is None:
            try:
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError("Install Google API dependencies before using Calendar.") from exc
            self._service = build("calendar", "v3", credentials=self.oauth.credentials(CALENDAR_SCOPES), cache_discovery=False)
        return self._service

    def is_connected(self) -> bool:
        try:
            self._api().calendarList().list(maxResults=1).execute()
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        self._service = None
        self.oauth.revoke()

    def list_events(self, start: datetime, end: datetime, calendar_id: str = "primary") -> list[CalendarEvent]:
        data = self._api().events().list(calendarId=calendar_id, timeMin=_rfc3339(start), timeMax=_rfc3339(end), singleEvents=True, orderBy="startTime").execute()
        events = []
        for item in data.get("items", []):
            s = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            e = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
            if not s or not e:
                continue
            events.append(CalendarEvent(item.get("summary") or "Untitled", _parse_google_time(s), _parse_google_time(e), calendar_id, item.get("id")))
        return events

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> CalendarEvent:
        body = {"summary": event.title, "start": _event_time(event.start), "end": _event_time(event.end)}
        item = self._api().events().insert(calendarId=calendar_id, body=body).execute()
        return CalendarEvent(item.get("summary") or event.title, _parse_google_time(item["start"].get("dateTime") or item["start"]["date"]), _parse_google_time(item["end"].get("dateTime") or item["end"]["date"]), calendar_id, item.get("id"))

    def update_event(self, event_id: str, event: CalendarEvent, calendar_id: str = "primary") -> CalendarEvent:
        body = {"summary": event.title, "start": _event_time(event.start), "end": _event_time(event.end)}
        item = self._api().events().update(calendarId=calendar_id, eventId=event_id, body=body).execute()
        return CalendarEvent(item.get("summary") or event.title, _parse_google_time(item["start"].get("dateTime") or item["start"]["date"]), _parse_google_time(item["end"].get("dateTime") or item["end"]["date"]), calendar_id, item.get("id"))

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        self._api().events().delete(calendarId=calendar_id, eventId=event_id).execute()

def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def _event_time(dt: datetime) -> dict[str, str]:
    return {"dateTime": _rfc3339(dt), "timeZone": "UTC"}

def _parse_google_time(value: str) -> datetime:
    if "T" not in value:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
