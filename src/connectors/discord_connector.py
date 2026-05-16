"""
Discord connector — read messages, send messages, list channels.
Uses discord.py library with a bot token.
Think of the bot as a member of your server that can read and
write messages on your behalf via the Discord API.

Unlike Slack's REST-only approach, Discord bots connect via
a persistent WebSocket Gateway to receive real-time events.
For Phoenix 03 we use HTTP REST only (no persistent connection)
since we just need to read/send on demand.

Requires in .env:
    DISCORD_BOT_TOKEN
    DISCORD_GUILD_ID    (your server ID)
"""

import os
from datetime import datetime
from typing import Any, Optional

import requests

from src.connectors.base_connector import BaseConnector
from src.models import Message, MessagePlatform


DISCORD_BASE_URL = "https://discord.com/api/v10"


class DiscordConnector(BaseConnector):

    def __init__(self):
        self._token   = os.getenv("DISCORD_BOT_TOKEN")
        self._guild   = os.getenv("DISCORD_GUILD_ID")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bot {self._token}",
            "Content-Type":  "application/json",
        })
        self._channel_cache: dict[str, str] = {}  # name → id

    def _get(self, path: str, params: dict = None) -> Any:
        resp = self._session.get(
            f"{DISCORD_BASE_URL}{path}",
            params=params or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> Any:
        resp = self._session.post(
            f"{DISCORD_BASE_URL}{path}",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def authenticate(self) -> bool:
        return self.health_check()

    def health_check(self) -> bool:
        if not self._token:
            print("[discord] No bot token configured.")
            return False
        try:
            self._get("/users/@me")
            return True
        except Exception as e:
            print(f"[discord] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "discord_list_channels",
                "description": "List all text channels in the Discord server.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   [],
                }
            },
            {
                "name":        "discord_read_messages",
                "description": "Read recent messages from a Discord channel.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type":        "string",
                            "description": "Channel name (e.g. 'general')"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Number of messages to fetch (default 10, max 100)"
                        }
                    },
                    "required": ["channel"]
                }
            },
            {
                "name":        "discord_send_message",
                "description": "Send a message to a Discord channel.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type":        "string",
                            "description": "Channel name to send to"
                        },
                        "message": {
                            "type":        "string",
                            "description": "Message content to send"
                        }
                    },
                    "required": ["channel", "message"]
                }
            },
            {
                "name":        "discord_get_members",
                "description": "List members in the Discord server.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type":        "integer",
                            "description": "Max members to return (default 10)"
                        }
                    },
                    "required": []
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "discord_list_channels": self._list_channels,
            "discord_read_messages": self._read_messages,
            "discord_send_message":  self._send_message,
            "discord_get_members":   self._get_members,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[discord] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _list_channels(self) -> list[dict]:
        data = self._get(f"/guilds/{self._guild}/channels")
        channels = [
            {
                "id":   ch["id"],
                "name": ch["name"],
                "type": "text" if ch["type"] == 0 else "other",
            }
            for ch in data
            if ch["type"] == 0  # 0 = text channel
        ]
        # Cache name → id for later lookups
        for ch in channels:
            self._channel_cache[ch["name"]] = ch["id"]
        return channels

    def _read_messages(self, channel: str, limit: int = 10) -> list[Message]:
        channel_id = self._resolve_channel(channel)
        if not channel_id:
            raise ValueError(f"[discord] Channel not found: {channel}")

        limit = min(limit, 100)
        data  = self._get(f"/channels/{channel_id}/messages", {"limit": limit})

        return [
            Message(
                id=m["id"],
                platform=MessagePlatform.SLACK,  # reusing — add DISCORD to enum in Phoenix 04
                sender=m["author"]["username"],
                channel=channel,
                content=m["content"],
                timestamp=datetime.fromisoformat(
                    m["timestamp"].replace("Z", "+00:00")
                ),
                thread_id=m.get("referenced_message", {}).get("id") if m.get("referenced_message") else None,
            )
            for m in data
            if m.get("content")  # skip empty/embed-only messages
        ]

    def _send_message(self, channel: str, message: str) -> dict:
        channel_id = self._resolve_channel(channel)
        if not channel_id:
            raise ValueError(f"[discord] Channel not found: {channel}")

        data = self._post(f"/channels/{channel_id}/messages", {"content": message})
        return {"id": data["id"], "channel": channel}

    def _get_members(self, limit: int = 10) -> list[dict]:
        data = self._get(f"/guilds/{self._guild}/members", {"limit": min(limit, 100)})
        return [
            {
                "username": m["user"]["username"],
                "id":       m["user"]["id"],
                "joined":   m.get("joined_at"),
                "roles":    m.get("roles", []),
            }
            for m in data
            if not m["user"].get("bot")  # exclude bots
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_channel(self, name: str) -> Optional[str]:
        """Resolve channel name to ID, using cache or fresh fetch."""
        name = name.lstrip("#")

        if name in self._channel_cache:
            return self._channel_cache[name]

        # Cache miss — fetch all channels
        self._list_channels()
        return self._channel_cache.get(name)
