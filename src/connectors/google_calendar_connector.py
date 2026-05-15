"""
Google Calendar connector — read events, create events, check availability.
Uses OAuth2 with offline access — the token is stored locally and
refreshes automatically when it expires.
Think of the token file as a long-term guest pass that renews itself
rather than making you log in every time.

Requires in .env:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_TOKEN_PATH   (default: certs/google_token.json)

First run will open a browser for OAuth consent.
Subsequent runs use the stored token silently.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import TIMEZONE

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.connectors.base_connector import BaseConnector
from src.connectors.google_auth import get_credentials
from src.models import CalendarEvent


class GoogleCalendarConnector(BaseConnector):

    def __init__(self):
        self._creds   = None
        self._service = None

    def authenticate(self) -> bool:
        try:
            self._creds   = get_credentials()
            self._service = build("calendar", "v3", credentials=self._creds)
            return True
        except Exception as e:
            print(f"[gcal] Authentication failed: {e}")
            return False

    def health_check(self) -> bool:
        if not self._service:
            return False
        try:
            self._service.calendarList().list(maxResults=1).execute()
            return True
        except Exception as e:
            print(f"[gcal] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "calendar_get_events",
                "description": "Get upcoming calendar events for a given date range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type":        "string",
                            "description": "Date to fetch events for (YYYY-MM-DD). Defaults to today."
                        },
                        "days_ahead": {
                            "type":        "integer",
                            "description": "Number of days ahead to look (default 1)"
                        },
                        "calendar_id": {
                            "type":        "string",
                            "description": "Calendar ID (default: primary)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name":        "calendar_create_event",
                "description": "Create a new event on Google Calendar.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type":        "string",
                            "description": "Event title"
                        },
                        "start": {
                            "type":        "string",
                            "description": "Start datetime (ISO format: YYYY-MM-DDTHH:MM:SS)"
                        },
                        "end": {
                            "type":        "string",
                            "description": "End datetime (ISO format: YYYY-MM-DDTHH:MM:SS)"
                        },
                        "description": {
                            "type":        "string",
                            "description": "Event description (optional)"
                        },
                        "attendees": {
                            "type":        "array",
                            "items":       {"type": "string"},
                            "description": "List of attendee email addresses (optional)"
                        },
                        "location": {
                            "type":        "string",
                            "description": "Event location (optional)"
                        }
                    },
                    "required": ["title", "start", "end"]
                }
            },
            {
                "name":        "calendar_list_calendars",
                "description": "List all calendars the user has access to.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
            {
                "name":        "calendar_check_availability",
                "description": "Check free/busy status for a given time range.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type":        "string",
                            "description": "Date to check (YYYY-MM-DD)"
                        },
                        "start_time": {
                            "type":        "string",
                            "description": "Start time (HH:MM)"
                        },
                        "end_time": {
                            "type":        "string",
                            "description": "End time (HH:MM)"
                        }
                    },
                    "required": ["date", "start_time", "end_time"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "calendar_get_events":       self._get_events,
            "calendar_create_event":     self._create_event,
            "calendar_list_calendars":   self._list_calendars,
            "calendar_check_availability": self._check_availability,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[gcal] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _get_events(
        self,
        date:        str = None,
        days_ahead:  int = 1,
        calendar_id: str = "primary"
    ) -> list[CalendarEvent]:

        if date:
            start = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        else:
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)

        end = start + timedelta(days=days_ahead)

        try:
            result = self._service.events().list(
                calendarId=calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            return [_parse_event(e) for e in result.get("items", [])]

        except HttpError as e:
            print(f"[gcal] Failed to get events: {e}")
            return []

    def _create_event(
        self,
        title:       str,
        start:       str,
        end:         str,
        description: str = None,
        attendees:   list[str] = None,
        location:    str = None,
    ) -> CalendarEvent:

        body = {
            "summary":  title,
            "start":    {"dateTime": start, "timeZone": TIMEZONE},
            "end":      {"dateTime": end,   "timeZone": TIMEZONE},
        }

        if description: body["description"] = description
        if location:    body["location"]    = location
        if attendees:   body["attendees"]   = [{"email": e} for e in attendees]

        try:
            event = self._service.events().insert(
                calendarId="primary",
                body=body,
            ).execute()
            return _parse_event(event)
        except HttpError as e:
            print(f"[gcal] Failed to create event: {e}")
            raise

    def _list_calendars(self) -> list[dict]:
        try:
            result = self._service.calendarList().list().execute()
            return [
                {
                    "id":      c["id"],
                    "name":    c["summary"],
                    "primary": c.get("primary", False),
                }
                for c in result.get("items", [])
            ]
        except HttpError as e:
            print(f"[gcal] Failed to list calendars: {e}")
            return []

    def _check_availability(
        self,
        date:       str,
        start_time: str,
        end_time:   str,
    ) -> dict:
        """Check if a time slot is free."""
        start = datetime.fromisoformat(f"{date}T{start_time}:00").replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(f"{date}T{end_time}:00").replace(tzinfo=timezone.utc)

        try:
            result = self._service.freebusy().query(body={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items":   [{"id": "primary"}],
            }).execute()

            busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
            return {
                "is_free": len(busy) == 0,
                "busy_slots": busy,
            }
        except HttpError as e:
            print(f"[gcal] Failed to check availability: {e}")
            raise


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_event(e: dict) -> CalendarEvent:
    """Parse a Google Calendar API event into our CalendarEvent model."""
    start_raw = e.get("start", {})
    end_raw   = e.get("end", {})

    start = datetime.fromisoformat(
        start_raw.get("dateTime", start_raw.get("date", ""))
    )
    end = datetime.fromisoformat(
        end_raw.get("dateTime", end_raw.get("date", ""))
    )

    return CalendarEvent(
        id=e.get("id", ""),
        title=e.get("summary", "No title"),
        start=start,
        end=end,
        location=e.get("location"),
        description=e.get("description"),
        attendees=[a["email"] for a in e.get("attendees", [])],
    )

# First run opens a browser
# — that's expected for Google OAuth.
# After that the token auto-refreshes silently.
