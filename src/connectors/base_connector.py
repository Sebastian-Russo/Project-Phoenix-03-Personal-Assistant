"""
Abstract base class all connectors must implement.
Same contract as Phoenix 02 but extended for agents —
connectors now also expose their capabilities as tool definitions
so the orchestrator knows what each one can do.

Think of it as a job posting: the connector lists its skills,
and the orchestrator matches them to incoming requests.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Verify credentials and establish connection.
        Called once at startup. Returns True if ready, False otherwise.
        Unlike Phoenix 02's health_check, this may trigger an OAuth flow.
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """
        Fast liveness check — no side effects, no OAuth.
        Called before every agent operation to verify the
        connector is still authenticated and reachable.
        """
        ...

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """
        Return this connector's capabilities as Claude tool definitions.
        These get registered in the tool registry and handed to Claude
        so it knows what actions are available.

        Each tool definition follows Anthropic's tool use format:
        {
            "name":        "slack_read_messages",
            "description": "Read unread messages from a Slack channel",
            "input_schema": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Channel name"},
                    "limit":   {"type": "integer", "description": "Max messages"}
                },
                "required": ["channel"]
            }
        }
        """
        ...

    @abstractmethod
    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        """
        Execute a tool by name with the given parameters.
        The orchestrator calls this after Claude decides which tool to use.
        Returns raw data — the agent layer handles formatting.
        """
        ...

# The key difference from Phoenix 02
# — get_tools() and execute_tool().
# In Phoenix 02 connectors had fixed methods (get_accounts, get_bills).
# Here each connector advertises its capabilities as Claude tool definitions,
# and the orchestrator dynamically discovers what's available.
# Claude reads those definitions and decides which ones to call based on the user's request.
