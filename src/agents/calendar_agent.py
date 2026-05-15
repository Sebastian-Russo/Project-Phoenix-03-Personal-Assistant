"""
Calendar agent — read events, create events, check availability.
Wraps GoogleCalendarConnector with Claude-powered natural language
date parsing and scheduling intelligence.

Think of it as a smart assistant that understands "next Tuesday afternoon"
and turns it into an actual calendar event without you specifying
exact times or ISO date formats.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import anthropic

from src.models import AgentRequest, AgentResponse, AgentType, CalendarEvent, CalendarSummary
from src.connectors.google_calendar_connector import GoogleCalendarConnector


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class CalendarAgent:

    def __init__(self, calendar_connector: GoogleCalendarConnector):
        self._calendar = calendar_connector
        self._client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        Route to the correct calendar action.
        request.parameters expected:
            action      — "get_events", "create_event", "check_availability", "summary"
            date        — date string (natural language or ISO)
            title       — event title (for create)
            start       — start datetime (for create)
            end         — end datetime (for create)
            description — event description (for create)
            attendees   — list of emails (for create)
        """
        action = request.parameters.get("action", "summary")

        handlers = {
            "get_events":         self._get_events,
            "create_event":       self._create_event,
            "check_availability": self._check_availability,
            "summary":            self._daily_summary,
        }

        handler = handlers.get(action)
        if not handler:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response=f"Unknown action: {action}. Valid: {list(handlers.keys())}",
                errors=[f"Unknown action: {action}"],
            )

        return handler(request)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _get_events(self, request: AgentRequest) -> AgentResponse:
        """Get events for a given date or date range."""
        params     = request.parameters
        date_input = params.get("date", "today")
        days_ahead = params.get("days_ahead", 1)

        # Resolve natural language date
        date_iso = self._resolve_date(date_input, request.context)

        try:
            events = self._calendar.execute_tool("calendar_get_events", {
                "date":       date_iso,
                "days_ahead": days_ahead,
            })

            if not events:
                return AgentResponse(
                    success=True,
                    agent=AgentType.CALENDAR,
                    response=f"No events found for {date_input}.",
                    data=[],
                )

            formatted = self._format_events(events)

            return AgentResponse(
                success=True,
                agent=AgentType.CALENDAR,
                response=formatted,
                data=events,
                actions_taken=[f"Fetched {len(events)} events for {date_input}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response=f"Failed to get events: {e}",
                errors=[str(e)],
            )

    def _create_event(self, request: AgentRequest) -> AgentResponse:
        """
        Create a calendar event.
        If start/end are natural language, Claude resolves them first.
        """
        params = request.parameters

        title = params.get("title")
        if not title:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response="Please provide an event title.",
                errors=["Missing title"],
            )

        # Resolve natural language times if needed
        start = params.get("start")
        end   = params.get("end")

        if not start or not end:
            resolved = self._resolve_event_times(
                raw_input=request.raw_input,
                context=request.context,
            )
            start = start or resolved.get("start")
            end   = end   or resolved.get("end")

        if not start or not end:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response="Could not determine event start/end time. Please specify them.",
                errors=["Missing start or end time"],
            )

        try:
            event = self._calendar.execute_tool("calendar_create_event", {
                "title":       title,
                "start":       start,
                "end":         end,
                "description": params.get("description"),
                "attendees":   params.get("attendees", []),
                "location":    params.get("location"),
            })

            start_dt = datetime.fromisoformat(start)
            response = (
                f"Created **{title}** on "
                f"{start_dt.strftime('%A, %B %d at %I:%M %p')}."
            )

            if params.get("attendees"):
                response += f" Invited: {', '.join(params['attendees'])}."

            return AgentResponse(
                success=True,
                agent=AgentType.CALENDAR,
                response=response,
                data=event,
                actions_taken=[f"Created event: {title}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response=f"Failed to create event: {e}",
                errors=[str(e)],
            )

    def _check_availability(self, request: AgentRequest) -> AgentResponse:
        """Check if a time slot is free."""
        params = request.parameters
        date   = params.get("date")
        start  = params.get("start_time")
        end    = params.get("end_time")

        if not all([date, start, end]):
            # Try to resolve from natural language
            resolved = self._resolve_event_times(request.raw_input, request.context)
            date  = date  or resolved.get("date")
            start = start or resolved.get("start_time")
            end   = end   or resolved.get("end_time")

        try:
            result = self._calendar.execute_tool("calendar_check_availability", {
                "date":       date,
                "start_time": start,
                "end_time":   end,
            })

            if result["is_free"]:
                response = f"You're free from {start} to {end} on {date}."
            else:
                busy = result["busy_slots"]
                response = f"You have {len(busy)} conflict(s) from {start} to {end} on {date}."

            return AgentResponse(
                success=True,
                agent=AgentType.CALENDAR,
                response=response,
                data=result,
                actions_taken=[f"Checked availability for {date} {start}-{end}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response=f"Failed to check availability: {e}",
                errors=[str(e)],
            )

    def _daily_summary(self, request: AgentRequest) -> AgentResponse:
        """Get a natural language summary of today's calendar."""
        date_input = request.parameters.get("date", "today")
        date_iso   = self._resolve_date(date_input, request.context)

        try:
            events = self._calendar.execute_tool("calendar_get_events", {
                "date":       date_iso,
                "days_ahead": 1,
            })

            if not events:
                return AgentResponse(
                    success=True,
                    agent=AgentType.CALENDAR,
                    response=f"Nothing on your calendar for {date_input}. Clear day.",
                    data=[],
                )

            summary = self._claude_summarize_day(date_input, events)

            return AgentResponse(
                success=True,
                agent=AgentType.CALENDAR,
                response=summary,
                data=events,
                actions_taken=[f"Summarized {len(events)} events for {date_input}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.CALENDAR,
                response=f"Failed to get calendar summary: {e}",
                errors=[str(e)],
            )

    # ── Claude helpers ────────────────────────────────────────────────────────

    def _resolve_date(self, date_input: str, context: list[dict]) -> str:
        """
        Convert natural language date to ISO format.
        'today' → '2026-05-15'
        'next Tuesday' → '2026-05-19'
        'tomorrow' → '2026-05-16'
        """
        today = datetime.now(timezone.utc)

        simple = {
            "today":     today,
            "tomorrow":  today + timedelta(days=1),
            "yesterday": today - timedelta(days=1),
        }

        if date_input.lower() in simple:
            return simple[date_input.lower()].strftime("%Y-%m-%d")

        # Already ISO format
        try:
            datetime.fromisoformat(date_input)
            return date_input[:10]
        except ValueError:
            pass

        # Ask Claude to resolve it
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": f"""Today is {today.strftime('%Y-%m-%d (%A)')}.
Convert this date reference to ISO format (YYYY-MM-DD): "{date_input}"
Respond with only the date, nothing else."""
            }]
        )
        return resp.content[0].text.strip()

    def _resolve_event_times(self, raw_input: str, context: list[dict]) -> dict:
        """
        Extract date, start time, and end time from natural language.
        "Schedule a meeting next Tuesday at 2pm for an hour"
        → {date: "2026-05-19", start: "14:00", end: "15:00",
           start_iso: "2026-05-19T14:00:00", end_iso: "2026-05-19T15:00:00"}
        """
        today = datetime.now(timezone.utc)

        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": f"""Today is {today.strftime('%Y-%m-%d %H:%M (%A)')}.
Extract the event timing from this request: "{raw_input}"

Respond in this exact JSON format:
{{"date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM", "start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}}

If duration not specified, assume 1 hour.
Only return valid JSON."""
            }]
        )

        import json
        try:
            return json.loads(resp.content[0].text.strip())
        except Exception:
            return {}

    def _claude_summarize_day(self, date_label: str, events: list[CalendarEvent]) -> str:
        """Generate a natural language day summary."""
        event_list = "\n".join([
            f"- {e.start.strftime('%I:%M %p')} to {e.end.strftime('%I:%M %p')}: {e.title}"
            + (f" (with {', '.join(e.attendees[:2])})" if e.attendees else "")
            for e in events
        ])

        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": f"""Summarize this calendar for {date_label} in 2-3 sentences.
Note the busiest period and any back-to-back meetings.

Events:
{event_list}"""
            }]
        )
        return resp.content[0].text.strip()

    # ── Formatting ────────────────────────────────────────────────────────────

    def _format_events(self, events: list[CalendarEvent]) -> str:
        """Format a list of events for display."""
        lines = []
        for e in events:
            line = f"• **{e.title}** — {e.start.strftime('%I:%M %p')} to {e.end.strftime('%I:%M %p')}"
            if e.location:
                line += f" @ {e.location}"
            if e.attendees:
                line += f"\n  Attendees: {', '.join(e.attendees[:3])}"
                if len(e.attendees) > 3:
                    line += f" +{len(e.attendees)-3} more"
            lines.append(line)
        return "\n".join(lines)

# The _resolve_date and _resolve_event_times methods are the core value add here
# — instead of requiring ISO format input,
# the agent uses Claude to parse natural language like "next Tuesday at 2pm for an hour"
# into exact datetimes before passing to the connector.
# The connector never sees ambiguous input.
