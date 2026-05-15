"""
Briefing agent — morning briefing in one command.
Pulls from all connected services and delivers a single
natural language summary: calendar, messages, and anything else
that's relevant to your day.

Think of it as your morning standup with yourself —
what's happening, what needs attention, what can wait.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import anthropic

from src.models import AgentRequest, AgentResponse, AgentType
from src.connectors.slack_connector import SlackConnector
from src.connectors.google_calendar_connector import GoogleCalendarConnector
from src.connectors.spotify_connector import SpotifyConnector


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class BriefingAgent:

    def __init__(
        self,
        calendar_connector: GoogleCalendarConnector,
        slack_connector:    Optional[SlackConnector] = None,
        spotify_connector:  Optional[SpotifyConnector] = None,
    ):
        self._calendar = calendar_connector
        self._slack    = slack_connector
        self._spotify  = spotify_connector
        self._client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        Run the full morning briefing.
        Collects data from all available connectors in parallel,
        then synthesizes into a single natural language summary.
        """
        today    = datetime.now(timezone.utc)
        sections = []
        errors   = []
        actions  = []

        # ── Calendar ──────────────────────────────────────────────────────────
        try:
            events = self._calendar.execute_tool("calendar_get_events", {
                "date":       today.strftime("%Y-%m-%d"),
                "days_ahead": 1,
            })
            if events:
                sections.append(("calendar", events))
                actions.append(f"Fetched {len(events)} calendar events")
            else:
                sections.append(("calendar", []))
        except Exception as e:
            errors.append(f"Calendar: {e}")
            print(f"[briefing] Calendar fetch failed: {e}")

        # ── Slack unread ───────────────────────────────────────────────────────
        if self._slack:
            try:
                unread = self._slack.execute_tool("slack_get_unread", {})
                if unread:
                    sections.append(("slack", unread))
                    total = sum(ch["unread_count"] for ch in unread)
                    actions.append(f"Fetched {total} unread Slack messages")
            except Exception as e:
                errors.append(f"Slack: {e}")
                print(f"[briefing] Slack fetch failed: {e}")

        # ── Now playing (optional context) ────────────────────────────────────
        now_playing = None
        if self._spotify:
            try:
                result = self._spotify.execute_tool("spotify_now_playing", {})
                if result.get("track"):
                    now_playing = result
            except Exception:
                pass  # non-critical, skip silently

        # ── Synthesize with Claude ────────────────────────────────────────────
        briefing = self._synthesize(today, sections, now_playing)

        return AgentResponse(
            success=True,
            agent=AgentType.BRIEFING,
            response=briefing,
            data={"sections": len(sections), "errors": errors},
            actions_taken=actions,
            errors=errors,
        )

    def _synthesize(
        self,
        today:       datetime,
        sections:    list[tuple],
        now_playing: Optional[dict],
    ) -> str:
        """
        Use Claude to synthesize all data into a cohesive morning briefing.
        Raw data in, natural language briefing out.
        """
        context_parts = []

        for section_type, data in sections:
            if section_type == "calendar":
                if data:
                    event_lines = "\n".join([
                        f"  - {e.start.strftime('%I:%M %p')}: {e.title}"
                        + (f" (with {', '.join(e.attendees[:2])})" if e.attendees else "")
                        for e in data
                    ])
                    context_parts.append(f"CALENDAR ({len(data)} events):\n{event_lines}")
                else:
                    context_parts.append("CALENDAR: No events today.")

            elif section_type == "slack":
                slack_lines = []
                for ch in data:
                    slack_lines.append(
                        f"  - #{ch['channel']}: {ch['unread_count']} unread"
                    )
                    # Add first message preview
                    if ch["messages"]:
                        first = ch["messages"][0]
                        preview = first.content[:80]
                        if len(first.content) > 80:
                            preview += "..."
                        slack_lines.append(f"    Latest: {first.sender}: {preview}")
                context_parts.append(f"SLACK UNREAD:\n" + "\n".join(slack_lines))

        if now_playing:
            context_parts.append(
                f"NOW PLAYING: {now_playing['track']} by {now_playing['artist']}"
            )

        context = "\n\n".join(context_parts) if context_parts else "No data available."

        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": f"""Generate a concise morning briefing for {today.strftime('%A, %B %d')}.

Data:
{context}

Format:
- Start with a one-line day overview
- Calendar: list events with times, flag back-to-back meetings
- Messages: summarize what needs attention, skip noise
- End with one actionable priority for the day

Keep it under 200 words. Be direct, not cheerful."""
            }]
        )

        return resp.content[0].text.strip()
