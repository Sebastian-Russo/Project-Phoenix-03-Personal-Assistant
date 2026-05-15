"""
Short-term conversation memory for the orchestrator.
Think of it as a whiteboard that gets erased when the conversation ends —
it holds just enough context for Claude to understand follow-up messages
like "reply to that" or "add it to my calendar" without re-explaining.

This is different from Phoenix 01's knowledge base (long-term, persistent).
This is session memory — lives in RAM, gone when the server restarts.

For Phoenix 04, this plugs directly into Phoenix 01's knowledge base
so the assistant remembers across sessions.
"""

from datetime import datetime
from typing import Optional
from src.models import Turn


class ContextStore:

    def __init__(self, max_turns: int = 20):
        """
        max_turns — how many exchanges to keep in memory.
        Beyond this, oldest turns are dropped to keep the context
        window from growing indefinitely.
        20 turns covers most conversations without bloating API calls.
        """
        self._sessions: dict[str, list[Turn]] = {}
        self._max_turns = max_turns

    def add_turn(self, session_id: str, role: str, content: str, tools_used: list[str] = None) -> None:
        """Add a single turn to a session's history."""
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        self._sessions[session_id].append(Turn(
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            tools_used=tools_used or [],
        ))

        # Trim oldest turns if over limit
        if len(self._sessions[session_id]) > self._max_turns:
            self._sessions[session_id] = self._sessions[session_id][-self._max_turns:]

    def get_history(self, session_id: str) -> list[dict]:
        """
        Return conversation history in Claude API format.
        Claude expects: [{"role": "user", "content": "..."}, ...]
        """
        turns = self._sessions.get(session_id, [])
        return [
            {"role": turn.role, "content": turn.content}
            for turn in turns
        ]

    def get_last_turn(self, session_id: str) -> Optional[Turn]:
        """Return the most recent turn for a session."""
        turns = self._sessions.get(session_id, [])
        return turns[-1] if turns else None

    def inject_context(self, session_id: str, key: str, value: str) -> None:
        """
        Inject a system-level context note into the conversation.
        Used to pass structured data back to Claude without showing
        it to the user — e.g. "The last Slack message was from Sarah at 3pm."

        This lets follow-up messages like "reply to her" work correctly
        because Claude has the reference in its history.
        """
        content = f"[context:{key}] {value}"
        self.add_turn(session_id, "user", content)

    def clear(self, session_id: str) -> None:
        """Clear history for a session."""
        self._sessions.pop(session_id, None)

    def active_sessions(self) -> list[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())

    def session_length(self, session_id: str) -> int:
        """Return number of turns in a session."""
        return len(self._sessions.get(session_id, []))

# The inject_context() method is the non-obvious one
# — it's how the system maintains references across turns.
# When you say "reply to that message", Claude needs to know what "that" refers to.
# After reading your Slack messages the orchestrator injects the message details into context,
# so the next turn Claude can resolve the reference without you repeating yourself.
