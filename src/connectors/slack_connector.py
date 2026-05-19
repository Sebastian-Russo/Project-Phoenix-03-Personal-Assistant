"""
Slack connector — read messages, send messages, list channels.
Uses xoxe rotation-enabled tokens. When the access token expires,
we use the refresh token to get a new one automatically.
Think of it like a hotel key card that auto-renews before it expires.

Requires in .env:
    SLACK_ACCESS_TOKEN
    SLACK_REFRESH_TOKEN
    SLACK_CLIENT_ID
    SLACK_CLIENT_SECRET
"""

import os
from datetime import datetime
from typing import Any

import requests

from src.connectors.base_connector import BaseConnector
from src.models import Message, MessagePlatform


SLACK_BASE_URL = "https://slack.com/api"


class SlackConnector(BaseConnector):

    def __init__(self):
        self._access_token  = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_ACCESS_TOKEN")  # ← changed
        self._refresh_token = os.getenv("SLACK_REFRESH_TOKEN")
        self._client_id     = os.getenv("SLACK_CLIENT_ID")
        self._client_secret = os.getenv("SLACK_CLIENT_SECRET")
        self._session       = requests.Session()
        self._user_cache: dict[str, str] = {}  # user_id → display name

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """Verify token is valid, attempt refresh if not."""
        if self._test_token():
            return True
        print("[slack] Access token invalid — attempting refresh...")
        return self._refresh_access_token()

    def health_check(self) -> bool:
        return self._test_token()

    def _test_token(self) -> bool:
        try:
            resp = self._get("auth.test")
            return resp.get("ok", False)
        except Exception as e:
            print(f"[slack] Health check failed: {e}")
            return False

    def _refresh_access_token(self) -> bool:
        """
        Use refresh token to get a new access token.
        Slack xoxe tokens rotate — this keeps us authenticated
        without manual re-login.
        """
        if not all([self._refresh_token, self._client_id, self._client_secret]):
            print("[slack] Cannot refresh — missing refresh token or client credentials.")
            return False
        try:
            resp = requests.post(
                f"{SLACK_BASE_URL}/tooling.tokens.rotate",
                headers={"Authorization": f"Bearer {self._refresh_token}"},
                data={"refresh_token": self._refresh_token},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok"):
                self._access_token  = data["token"]
                self._refresh_token = data["refresh_token"]
                # Persist new tokens to .env would require file write —
                # for now store in memory only. Phoenix 04 will persist via vault.
                print("[slack] Token rotated successfully.")
                return True
            print(f"[slack] Token rotation failed: {data.get('error')}")
            return False
        except Exception as e:
            print(f"[slack] Token rotation error: {e}")
            return False

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, method: str, params: dict = None) -> dict:
        resp = self._session.get(
            f"{SLACK_BASE_URL}/{method}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, method: str, payload: dict) -> dict:
        resp = self._session.post(
            f"{SLACK_BASE_URL}/{method}",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Tools ─────────────────────────────────────────────────────────────────

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "slack_list_channels",
                "description": "List all Slack channels the bot has access to.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   [],
                }
            },
            {
                "name":        "slack_read_messages",
                "description": "Read recent messages from a Slack channel or DM.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type":        "string",
                            "description": "Channel name (e.g. 'general') or user name for DMs"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Number of messages to fetch (default 10)"
                        }
                    },
                    "required": ["channel"]
                }
            },
            {
                "name":        "slack_send_message",
                "description": "Send a message to a Slack channel or user.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type":        "string",
                            "description": "Channel name or user name to send to"
                        },
                        "message": {
                            "type":        "string",
                            "description": "Message text to send"
                        },
                        "thread_ts": {
                            "type":        "string",
                            "description": "Thread timestamp to reply in a thread (optional)"
                        }
                    },
                    "required": ["channel", "message"]
                }
            },
            {
                "name":        "slack_get_unread",
                "description": "Get all unread messages across all channels.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   [],
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "slack_list_channels": self._list_channels,
            "slack_read_messages": self._read_messages,
            "slack_send_message":  self._send_message,
            "slack_get_unread":    self._get_unread,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[slack] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _list_channels(self) -> list[dict]:
        data     = self._get("conversations.list", {"types": "public_channel,private_channel"})
        channels = data.get("channels", [])
        return [
            {"id": c["id"], "name": c["name"], "is_private": c.get("is_private", False)}
            for c in channels
        ]

    def _read_messages(self, channel: str, limit: int = 10) -> list[Message]:
        """Read messages from a channel by name."""
        channel_id = self._resolve_channel(channel)
        if not channel_id:
            raise ValueError(f"[slack] Channel not found: {channel}")

        data     = self._get("conversations.history", {"channel": channel_id, "limit": limit})
        messages = data.get("messages", [])

        return [
            Message(
                id=m["ts"],
                platform=MessagePlatform.SLACK,
                sender=self._resolve_user(m.get("user", "unknown")),
                channel=channel,
                content=m.get("text", ""),
                timestamp=datetime.fromtimestamp(float(m["ts"])),
                thread_id=m.get("thread_ts"),
            )
            for m in messages
        ]

    def _send_message(self, channel: str, message: str, thread_ts: str = None) -> dict:
        channel_id = self._resolve_channel(channel)
        if not channel_id:
            raise ValueError(f"[slack] Channel not found: {channel}")

        payload = {"channel": channel_id, "text": message}
        if thread_ts:
            payload["thread_ts"] = thread_ts

        data = self._post("chat.postMessage", payload)
        return {"ok": data.get("ok"), "ts": data.get("ts")}

    def _get_unread(self) -> list[dict]:
        """
        Get unread messages across all channels.
        Slack doesn't have a single 'get all unread' endpoint —
        we fetch channels, then check each one for unread counts.
        """
        channels = self._list_channels()
        unread   = []

        for ch in channels:
            try:
                info = self._get("conversations.info", {"channel": ch["id"]})
                channel_data = info.get("channel", {})
                unread_count = channel_data.get("unread_count", 0)

                if unread_count > 0:
                    messages = self._read_messages(ch["name"], limit=unread_count)
                    unread.append({
                        "channel":       ch["name"],
                        "unread_count":  unread_count,
                        "messages":      messages,
                    })
            except Exception as e:
                print(f"[slack] Failed to check unread for {ch['name']}: {e}")

        return unread

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_channel(self, name: str) -> str | None:
        """Resolve a channel name to its ID."""
        name = name.lstrip("#")
        data = self._get("conversations.list", {
            "types": "public_channel,private_channel,im",
            "limit": 200,
        })
        for ch in data.get("channels", []):
            if ch.get("name") == name:
                return ch["id"]
        return None

    def _resolve_user(self, user_id: str) -> str:
        """Resolve a user ID to a display name, with caching."""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            data = self._get("users.info", {"user": user_id})
            name = data.get("user", {}).get("display_name") or \
                   data.get("user", {}).get("real_name", user_id)
            self._user_cache[user_id] = name
            return name
        except Exception:
            return user_id

# Token rotation is the main new concept here
# — xoxe tokens expire and need refreshing via tooling.tokens.rotate.
# The connector handles that automatically so the orchestrator never has to think about auth state.
