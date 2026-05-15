"""
Spotify connector — control playback, search tracks, manage playlists.
Uses Authorization Code flow with manual code paste for OAuth.
Spotify requires https for redirect URIs which breaks local HTTP servers,
so after browser approval the user pastes the redirect URL into the terminal.

Requires in .env:
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
    SPOTIFY_REDIRECT_URI    (https://localhost:8888/callback)
    SPOTIFY_TOKEN_PATH      (default: certs/spotify_token.json)
"""

import json
import os
import time
import webbrowser
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from src.connectors.base_connector import BaseConnector


SPOTIFY_AUTH_URL  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_BASE_URL  = "https://api.spotify.com/v1"

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "streaming",
])

TOKEN_PATH    = os.getenv("SPOTIFY_TOKEN_PATH",    "certs/spotify_token.json")
CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI",  "http://127.0.0.1:8888/callback")

# ── Token management ──────────────────────────────────────────────────────────

def _load_token() -> Optional[dict]:
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH) as f:
        return json.load(f)


def _save_token(token: dict) -> None:
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump(token, f)


def _refresh_token(refresh_token: str) -> dict:
    """Exchange refresh token for a new access token."""
    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = time.time() + token["expires_in"]
    if "refresh_token" not in token:
        token["refresh_token"] = refresh_token
    return token


def _run_auth_flow() -> dict:
    """
    Manual auth flow — opens browser, user copies the redirect URL.
    Spotify requires https for redirect URIs which breaks local HTTP
    server callback capture, so we ask the user to paste the URL instead.
    Think of it as catching the callback by hand rather than with a net.
    """
    auth_params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
    }
    auth_url = f"{SPOTIFY_AUTH_URL}?{urlencode(auth_params)}"

    print(f"\n[spotify] Opening browser for Spotify authorization...")
    print(f"[spotify] If browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("[spotify] After approving, your browser will redirect to a URL")
    print("[spotify] starting with http://127.0.0.1:8888/callback?code=...")
    print("[spotify] The page will show an error — that's expected.")
    print("[spotify] Copy the full URL from the address bar and paste it here:\n")
    callback_url = input("Paste redirect URL: ").strip()

    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)

    if "code" not in params:
        raise RuntimeError(
            "[spotify] No code found in pasted URL. "
            "Make sure to copy the full URL including ?code=..."
        )

    auth_code = params["code"][0]
    print(f"[spotify] Using redirect URI: {REDIRECT_URI}")

    resp = requests.post(
        SPOTIFY_TOKEN_URL,
        data={
            "grant_type":    "authorization_code",
            "code":          auth_code,
            "redirect_uri":  REDIRECT_URI,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = time.time() + token["expires_in"]
    return token


class SpotifyConnector(BaseConnector):

    def __init__(self):
        self._token:   Optional[dict] = None
        self._session: requests.Session = requests.Session()

    def authenticate(self) -> bool:
        token = _load_token()

        if token:
            if time.time() >= token.get("expires_at", 0) - 60:
                print("[spotify] Token expired — refreshing...")
                try:
                    token = _refresh_token(token["refresh_token"])
                    _save_token(token)
                except Exception as e:
                    print(f"[spotify] Refresh failed: {e}")
                    token = None

        if not token:
            print("[spotify] No valid token — running auth flow...")
            try:
                token = _run_auth_flow()
                _save_token(token)
            except Exception as e:
                print(f"[spotify] Auth flow failed: {e}")
                return False

        self._token = token
        return True

    def health_check(self) -> bool:
        if not self._token:
            return False
        if time.time() >= self._token.get("expires_at", 0) - 60:
            try:
                self._token = _refresh_token(self._token["refresh_token"])
                _save_token(self._token)
            except Exception:
                return False
        try:
            self._get("/me")
            return True
        except Exception as e:
            print(f"[spotify] Health check failed: {e}")
            return False

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self._session.get(
            f"{SPOTIFY_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self._token['access_token']}"},
            params=params or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, payload: dict = None, params: dict = None) -> Optional[dict]:
        resp = self._session.put(
            f"{SPOTIFY_BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {self._token['access_token']}",
                "Content-Type":  "application/json",
            },
            json=payload or {},
            params=params or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def _post(self, path: str, payload: dict = None) -> Optional[dict]:
        resp = self._session.post(
            f"{SPOTIFY_BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {self._token['access_token']}",
                "Content-Type":  "application/json",
            },
            json=payload or {},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "spotify_play",
                "description": "Play a song, artist, album, or playlist on Spotify.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "What to play — song name, artist, playlist name, or genre"
                        },
                        "type": {
                            "type":        "string",
                            "enum":        ["track", "album", "playlist", "artist"],
                            "description": "Type of content to search for (default: track)"
                        },
                        "device_name": {
                            "type":        "string",
                            "description": "Name of the device to play on (optional, uses active device)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name":        "spotify_pause",
                "description": "Pause Spotify playback.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
            {
                "name":        "spotify_skip",
                "description": "Skip to the next track.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
            {
                "name":        "spotify_get_devices",
                "description": "List available Spotify playback devices.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
            {
                "name":        "spotify_set_volume",
                "description": "Set Spotify playback volume.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "volume": {
                            "type":        "integer",
                            "description": "Volume level 0-100"
                        }
                    },
                    "required": ["volume"]
                }
            },
            {
                "name":        "spotify_now_playing",
                "description": "Get the currently playing track.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "spotify_play":        self._play,
            "spotify_pause":       self._pause,
            "spotify_skip":        self._skip,
            "spotify_get_devices": self._get_devices,
            "spotify_set_volume":  self._set_volume,
            "spotify_now_playing": self._now_playing,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[spotify] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _play(self, query: str, type: str = "track", device_name: str = None) -> dict:
        results = self._get("/search", {"q": query, "type": type, "limit": 1})
        items   = results.get(f"{type}s", {}).get("items", [])

        if not items:
            raise ValueError(f"[spotify] Nothing found for: {query}")

        item = items[0]
        uri  = item["uri"]

        device_id = None
        if device_name:
            device_id = self._resolve_device(device_name)

        payload = {}
        if type == "track":
            payload["uris"] = [uri]
        else:
            payload["context_uri"] = uri

        params = {"device_id": device_id} if device_id else {}
        self._put("/me/player/play", payload, params)

        return {
            "playing": item["name"],
            "type":    type,
            "uri":     uri,
            "device":  device_name or "active device",
        }

    def _pause(self) -> dict:
        self._put("/me/player/pause")
        return {"status": "paused"}

    def _skip(self) -> dict:
        self._post("/me/player/next")
        return {"status": "skipped"}

    def _get_devices(self) -> list[dict]:
        data = self._get("/me/player/devices")
        return [
            {
                "id":        d["id"],
                "name":      d["name"],
                "type":      d["type"],
                "is_active": d["is_active"],
                "volume":    d["volume_percent"],
            }
            for d in data.get("devices", [])
        ]

    def _set_volume(self, volume: int) -> dict:
        self._put("/me/player/volume", params={"volume_percent": max(0, min(100, volume))})
        return {"volume": volume}

    def _now_playing(self) -> dict:
        try:
            data = self._get("/me/player/currently-playing")
            if not data or not data.get("item"):
                return {"status": "nothing playing"}
            item = data["item"]
            return {
                "track":      item["name"],
                "artist":     ", ".join(a["name"] for a in item["artists"]),
                "album":      item["album"]["name"],
                "is_playing": data["is_playing"],
            }
        except Exception:
            return {"status": "nothing playing"}

    def _resolve_device(self, name: str) -> Optional[str]:
        devices = self._get_devices()
        for d in devices:
            if name.lower() in d["name"].lower():
                return d["id"]
        return None
