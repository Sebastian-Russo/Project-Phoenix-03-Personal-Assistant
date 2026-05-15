"""
Media agent — control Spotify playback via natural language.
Wraps SpotifyConnector with intent parsing so "play something
chill to focus" works just as well as "play playlist: Lo-Fi Beats".

Think of it as the voice interface layer for your speaker —
you say what you want, it figures out the exact Spotify query.
"""

import os
from typing import Any

import anthropic

from src.models import AgentRequest, AgentResponse, AgentType
from src.connectors.spotify_connector import SpotifyConnector


CLAUDE_MODEL = "claude-sonnet-4-20250514"


class MediaAgent:

    def __init__(self, spotify_connector: SpotifyConnector):
        self._spotify = spotify_connector
        self._client  = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def handle(self, request: AgentRequest) -> AgentResponse:
        """
        Route to correct media action.
        request.parameters expected:
            action      — "play", "pause", "skip", "volume", "now_playing", "devices"
            query       — what to play (for play action)
            type        — track/album/playlist/artist (for play)
            device_name — which device to play on (optional)
            volume      — 0-100 (for volume action)
        """
        action = request.parameters.get("action")

        # If no explicit action, infer from raw input
        if not action:
            action = self._infer_action(request.raw_input)

        handlers = {
            "play":        self._play,
            "pause":       self._pause,
            "skip":        self._skip,
            "volume":      self._set_volume,
            "now_playing": self._now_playing,
            "devices":     self._get_devices,
            "check_current":   self._now_playing,
            "current":         self._now_playing,
            "get_devices":     self._get_devices,
            "set_volume":      self._set_volume,
        }

        handler = handlers.get(action)
        if not handler:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Unknown action: {action}. Valid: {list(handlers.keys())}",
                errors=[f"Unknown action: {action}"],
            )

        return handler(request)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _play(self, request: AgentRequest) -> AgentResponse:
        params = request.parameters
        query  = params.get("query")

        # If no explicit query, extract from natural language
        if not query:
            query, content_type = self._extract_play_intent(request.raw_input)
        else:
            content_type = params.get("type", "track")

        if not query:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response="What would you like to play?",
                errors=["Missing query"],
            )

        device_name = params.get("device_name")

        try:
            result = self._spotify.execute_tool("spotify_play", {
                "query":       query,
                "type":        content_type,
                "device_name": device_name,
            })

            response = f"Playing **{result['playing']}**"
            if device_name:
                response += f" on {device_name}"
            response += "."

            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response=response,
                data=result,
                actions_taken=[f"Playing {content_type}: {query}"],
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Couldn't play that: {e}",
                errors=[str(e)],
            )

    def _pause(self, request: AgentRequest) -> AgentResponse:
        try:
            self._spotify.execute_tool("spotify_pause", {})
            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response="Paused.",
                actions_taken=["Paused playback"],
            )
        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Failed to pause: {e}",
                errors=[str(e)],
            )

    def _skip(self, request: AgentRequest) -> AgentResponse:
        try:
            self._spotify.execute_tool("spotify_skip", {})
            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response="Skipped to next track.",
                actions_taken=["Skipped track"],
            )
        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Failed to skip: {e}",
                errors=[str(e)],
            )

    def _set_volume(self, request: AgentRequest) -> AgentResponse:
        volume = request.parameters.get("volume")

        if volume is None:
            # Try to extract from natural language
            volume = self._extract_volume(request.raw_input)

        if volume is None:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response="Please specify a volume level (0-100).",
                errors=["Missing volume"],
            )

        try:
            self._spotify.execute_tool("spotify_set_volume", {"volume": int(volume)})
            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response=f"Volume set to {volume}%.",
                actions_taken=[f"Set volume to {volume}%"],
            )
        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Failed to set volume: {e}",
                errors=[str(e)],
            )

    def _now_playing(self, request: AgentRequest) -> AgentResponse:
        try:
            result = self._spotify.execute_tool("spotify_now_playing", {})

            if result.get("status") == "nothing playing":
                return AgentResponse(
                    success=True,
                    agent=AgentType.MEDIA,
                    response="Nothing is currently playing.",
                    data=result,
                )

            response = (
                f"Now playing **{result['track']}** by {result['artist']} "
                f"from *{result['album']}*."
            )
            if not result.get("is_playing"):
                response += " (Paused)"

            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response=response,
                data=result,
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Failed to get now playing: {e}",
                errors=[str(e)],
            )

    def _get_devices(self, request: AgentRequest) -> AgentResponse:
        try:
            devices = self._spotify.execute_tool("spotify_get_devices", {})

            if not devices:
                return AgentResponse(
                    success=True,
                    agent=AgentType.MEDIA,
                    response="No Spotify devices found. Open Spotify on a device first.",
                    data=[],
                )

            lines = [
                f"• **{d['name']}** ({d['type']}) — "
                f"{'🔊 Active' if d['is_active'] else 'Inactive'} "
                f"— Volume: {d['volume']}%"
                for d in devices
            ]

            return AgentResponse(
                success=True,
                agent=AgentType.MEDIA,
                response="Available Spotify devices:\n" + "\n".join(lines),
                data=devices,
            )

        except Exception as e:
            return AgentResponse(
                success=False,
                agent=AgentType.MEDIA,
                response=f"Failed to get devices: {e}",
                errors=[str(e)],
            )

    # ── Claude helpers ────────────────────────────────────────────────────────

    def _infer_action(self, raw_input: str) -> str:
        """
        Infer the media action from natural language.
        "pause the music" → "pause"
        "what's playing?" → "now_playing"
        "turn it up to 80" → "volume"
        """
        lower = raw_input.lower()

        if any(w in lower for w in ["pause", "stop", "mute"]):
            return "pause"
        if any(w in lower for w in ["skip", "next", "next track"]):
            return "skip"
        if any(w in lower for w in ["volume", "louder", "quieter", "turn up", "turn down"]):
            return "volume"
        if any(w in lower for w in ["what's playing", "now playing", "current", "what song"]):
            return "now_playing"
        if any(w in lower for w in ["devices", "speakers", "available"]):
            return "devices"
        return "play"

    def _extract_play_intent(self, raw_input: str) -> tuple[str, str]:
        """
        Extract what to play and what type it is from natural language.
        "play something chill" → ("chill", "playlist")
        "play Blinding Lights" → ("Blinding Lights", "track")
        "put on the Discover Weekly playlist" → ("Discover Weekly", "playlist")
        """
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"""Extract the Spotify search intent from: "{raw_input}"

Respond in JSON:
{{"query": "search query for Spotify", "type": "track|album|playlist|artist"}}

Examples:
"play something chill to focus" → {{"query": "chill focus", "type": "playlist"}}
"play Blinding Lights" → {{"query": "Blinding Lights", "type": "track"}}
"put on Discover Weekly" → {{"query": "Discover Weekly", "type": "playlist"}}
"play The Weeknd" → {{"query": "The Weeknd", "type": "artist"}}

Only return valid JSON."""
            }]
        )

        import json
        try:
            data = json.loads(resp.content[0].text.strip())
            return data.get("query", raw_input), data.get("type", "track")
        except Exception:
            return raw_input, "track"

    def _extract_volume(self, raw_input: str) -> int | None:
        """Extract volume level from natural language."""
        import re
        match = re.search(r"\b(\d{1,3})\b", raw_input)
        if match:
            val = int(match.group(1))
            if 0 <= val <= 100:
                return val

        lower = raw_input.lower()
        if "max" in lower or "full" in lower:
            return 100
        if "half" in lower:
            return 50
        if "low" in lower or "quiet" in lower:
            return 20

        return None
