"""
Data models for Phoenix 03.
Think of these as the vocabulary the entire system speaks —
every agent, connector, and tool uses these shapes to pass
information around without needing to know each other's internals.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from enum import Enum


class AgentType(Enum):
    ORCHESTRATOR = "orchestrator"
    MESSAGING    = "messaging"
    CALENDAR     = "calendar"
    MEDIA        = "media"
    VISION       = "vision"
    BRIEFING     = "briefing"


class ConnectorType(Enum):
    SLACK            = "slack"
    GOOGLE_CALENDAR  = "google_calendar"
    GOOGLE_DRIVE     = "google_drive"
    SPOTIFY          = "spotify"
    GITHUB           = "github"


class MessagePlatform(Enum):
    SLACK = "slack"
    EMAIL = "email"


class IntentType(Enum):
    """
    High-level intents the orchestrator can recognize.
    Think of these as the verbs of the system —
    what the user is trying to DO, not what they said.
    """
    READ_MESSAGES    = "read_messages"
    SEND_MESSAGE     = "send_message"
    READ_CALENDAR    = "read_calendar"
    CREATE_EVENT     = "create_event"
    PLAY_MUSIC       = "play_music"
    UPLOAD_FILE      = "upload_file"
    ANALYZE_IMAGE    = "analyze_image"
    READ_GITHUB      = "read_github"
    MORNING_BRIEFING = "morning_briefing"
    UNKNOWN          = "unknown"


# ── Messaging ─────────────────────────────────────────────────────────────────

@dataclass
class Message:
    """A single message from any platform."""
    id:          str
    platform:    MessagePlatform
    sender:      str
    channel:     str
    content:     str
    timestamp:   datetime
    thread_id:   Optional[str] = None
    is_unread:   bool = False


@dataclass
class MessageSummary:
    """Summarized view of messages — what the briefing agent returns."""
    platform:      MessagePlatform
    unread_count:  int
    summaries:     list[str]          # one line per important message
    action_items:  list[str]          # things requiring a response
    captured_at:   datetime = field(default_factory=datetime.utcnow)


# ── Calendar ──────────────────────────────────────────────────────────────────

@dataclass
class CalendarEvent:
    """A single calendar event."""
    id:          str
    title:       str
    start:       datetime
    end:         datetime
    location:    Optional[str] = None
    description: Optional[str] = None
    attendees:   list[str] = field(default_factory=list)
    calendar_id: str = "primary"


@dataclass
class CalendarSummary:
    """What the calendar agent returns for a briefing."""
    date:         datetime
    events:       list[CalendarEvent]
    next_event:   Optional[CalendarEvent] = None
    free_slots:   list[str] = field(default_factory=list)  # "2pm-4pm", etc.


# ── Media ─────────────────────────────────────────────────────────────────────

@dataclass
class SpotifyDevice:
    """A Spotify playback device (speaker, phone, computer)."""
    id:         str
    name:       str
    type:       str           # "Speaker", "Computer", "Smartphone"
    is_active:  bool
    volume:     int           # 0-100


@dataclass
class PlaybackRequest:
    """What to play and where."""
    query:       str                    # "something chill", "playlist: Focus"
    device_name: Optional[str] = None  # None = active device


# ── Vision ────────────────────────────────────────────────────────────────────

@dataclass
class ImageAnalysis:
    """Result of analyzing a photo."""
    content_type:  str                  # "form", "code", "document", "receipt", etc.
    extracted:     dict[str, Any]       # key-value pairs extracted from the image
    raw_text:      str                  # full text extracted
    suggested_destination: Optional[str] = None  # Drive folder or local path
    confidence:    float = 0.0


# ── Agent communication ───────────────────────────────────────────────────────

@dataclass
class AgentRequest:
    """
    What gets passed to any agent.
    Think of this as the envelope — the orchestrator fills it out
    and hands it to whichever agent needs to handle it.
    """
    intent:      IntentType
    raw_input:   str                    # original user message
    parameters:  dict[str, Any] = field(default_factory=dict)
    context:     list[dict] = field(default_factory=list)  # conversation history


@dataclass
class AgentResponse:
    """
    What every agent returns.
    Consistent shape means the orchestrator can handle any agent's
    response the same way without special-casing.
    """
    success:     bool
    agent:       AgentType
    response:    str                    # natural language response to user
    data:        Optional[Any] = None  # structured data if needed
    actions_taken: list[str] = field(default_factory=list)
    errors:      list[str] = field(default_factory=list)


# ── Conversation ──────────────────────────────────────────────────────────────

@dataclass
class Turn:
    """A single exchange in a conversation."""
    role:      str          # "user" or "assistant"
    content:   str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tools_used: list[str] = field(default_factory=list)

# The key addition over Phoenix 02 is AgentRequest and AgentResponse
# — the envelope system that lets the orchestrator talk to any agent without knowing its internals.
