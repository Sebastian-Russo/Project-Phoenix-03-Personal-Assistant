"""
Router — maps natural language input to the right agent and action.
Think of it as a traffic controller: reads the incoming request,
decides which agent handles it, and packages the parameters
so the agent doesn't have to parse raw text itself.

The router uses Claude to classify intent — not hardcoded keywords.
This means "throw on some tunes" routes to MediaAgent just as well
as "play music on Spotify".
"""

import json
import os
from typing import Optional

import anthropic

from src.models import AgentRequest, AgentType, IntentType


CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Maps intent → agent type
INTENT_TO_AGENT = {
    IntentType.READ_MESSAGES:    AgentType.MESSAGING,
    IntentType.SEND_MESSAGE:     AgentType.MESSAGING,
    IntentType.READ_CALENDAR:    AgentType.CALENDAR,
    IntentType.CREATE_EVENT:     AgentType.CALENDAR,
    IntentType.PLAY_MUSIC:       AgentType.MEDIA,
    IntentType.UPLOAD_FILE:      AgentType.VISION,
    IntentType.ANALYZE_IMAGE:    AgentType.VISION,
    IntentType.READ_GITHUB:      AgentType.ORCHESTRATOR,  # handled directly
    IntentType.MORNING_BRIEFING: AgentType.BRIEFING,
    IntentType.UNKNOWN:          AgentType.ORCHESTRATOR,  # orchestrator decides
}


class Router:

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def route(self, raw_input: str, context: list[dict] = None) -> AgentRequest:
        """
        Classify the user's input and build an AgentRequest.
        Returns a fully populated request ready for the orchestrator.
        """
        context = context or []
        intent, parameters = self._classify(raw_input, context)
        agent   = INTENT_TO_AGENT.get(intent, AgentType.ORCHESTRATOR)

        return AgentRequest(
            intent=intent,
            raw_input=raw_input,
            parameters=parameters,
            context=context,
        )

    def _classify(
        self,
        raw_input: str,
        context:   list[dict],
    ) -> tuple[IntentType, dict]:
        """
        Use Claude to classify the intent and extract parameters.
        Returns (intent, parameters dict).
        """
        # Build context summary for Claude
        context_str = ""
        if context:
            last = context[-3:]  # last 3 turns for context
            context_str = "\nRecent conversation:\n" + "\n".join([
                f"{t['role']}: {t['content'][:100]}"
                for t in last
            ])

        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": f"""Classify this request and extract parameters.

Request: "{raw_input}"{context_str}

Valid intents:
- read_messages: read/check/summarize Slack messages
- send_message: send/reply to a Slack message
- read_calendar: check calendar, get events, what's on schedule
- create_event: schedule/add/create a calendar event
- play_music: play/pause/skip/volume Spotify
- upload_file: upload a file to Drive
- analyze_image: analyze/read/extract from a photo or image
- read_github: check repos, issues, PRs, commits
- morning_briefing: morning briefing, daily summary, what's today
- unknown: anything else

Respond in this exact JSON format:
{{
    "intent": "one of the valid intents above",
    "parameters": {{
        "action": "specific sub-action if applicable",
        "channel": "slack channel if mentioned",
        "message": "message text if sending",
        "query": "search query or play query if applicable",
        "date": "date if mentioned",
        "title": "event title if creating",
        "destination": "drive or local if routing a file"
    }}
}}

Only include parameters that are explicitly mentioned. Return valid JSON only."""
            }]
        )

        try:
            data       = json.loads(resp.content[0].text.strip())
            intent_str = data.get("intent", "unknown")
            intent     = IntentType(intent_str)
            parameters = {k: v for k, v in data.get("parameters", {}).items() if v}
            return intent, parameters
        except Exception as e:
            print(f"[router] Classification failed: {e}")
            return IntentType.UNKNOWN, {}

    def get_agent_type(self, intent: IntentType) -> AgentType:
        """Return the agent type for a given intent."""
        return INTENT_TO_AGENT.get(intent, AgentType.ORCHESTRATOR)

# The router is the first place in Phoenix 03 where Claude does work that isn't about content
# — it's pure meta-reasoning.
# Claude reads the user's message and decides what kind of thing it is and what parameters to extract.
# No regex, no keyword matching, no hardcoded rules.
# "Throw on some tunes" and "play Spotify"
# both produce IntentType.PLAY_MUSIC with the right parameters.
