"""
ACRCloud connector — Shazam-style audio recognition.
Records audio from the microphone, sends it to ACRCloud's API,
and returns the identified song with metadata.

Think of it as holding your phone up to a speaker but programmatically —
capture a few seconds of audio, fingerprint it, match against 100M+ tracks.

Requires in .env:
    ACRCLOUD_ACCESS_KEY
    ACRCLOUD_ACCESS_SECRET
    ACRCLOUD_HOST

Install system dependency for audio recording:
    sudo apt-get install portaudio19-dev   (Linux)
    brew install portaudio                  (Mac)
    pip install pyaudio acrcloud-sdk
"""

import base64
import hashlib
import hmac
import http.client
import json
import os
import time
import urllib.parse
from datetime import datetime
from typing import Any, Optional

from src.connectors.base_connector import BaseConnector


ACRCLOUD_HOST       = os.getenv("ACRCLOUD_HOST", "identify-us-west-2.acrcloud.com")
ACRCLOUD_ACCESS_KEY = os.getenv("ACRCLOUD_ACCESS_KEY")
ACRCLOUD_SECRET     = os.getenv("ACRCLOUD_ACCESS_SECRET")
RECORD_SECONDS      = 8  # how long to listen before identifying


def _sign_request(string_to_sign: str, secret: str) -> str:
    """HMAC-SHA1 signature for ACRCloud API auth."""
    return base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha1,
        ).digest()
    ).decode("utf-8")


def _identify_audio(audio_bytes: bytes) -> dict:
    """
    Send raw audio bytes to ACRCloud and return identification result.
    Uses raw HTTP to avoid requiring the ACRCloud SDK.
    """
    timestamp   = str(int(time.time()))
    method      = "POST"
    uri         = "/v1/identify"
    data_type   = "audio"
    signature_version = "1"

    string_to_sign = "\n".join([
        method, uri, ACRCLOUD_ACCESS_KEY,
        data_type, signature_version, timestamp
    ])

    signature = _sign_request(string_to_sign, ACRCLOUD_SECRET)

    # Build multipart form
    boundary = "----ACRCloudBoundary"
    body  = f"--{boundary}\r\n"
    body += f'Content-Disposition: form-data; name="sample"; filename="sample.wav"\r\n'
    body += "Content-Type: audio/wav\r\n\r\n"
    body  = body.encode("utf-8") + audio_bytes + b"\r\n"

    fields = {
        "access_key":        ACRCLOUD_ACCESS_KEY,
        "sample_bytes":      str(len(audio_bytes)),
        "timestamp":         timestamp,
        "signature":         signature,
        "data_type":         data_type,
        "signature_version": signature_version,
    }

    for key, val in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        body += f"{val}\r\n".encode()

    body += f"--{boundary}--\r\n".encode()

    conn = http.client.HTTPSConnection(ACRCLOUD_HOST)
    conn.request(
        "POST", uri, body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    resp = conn.getresponse()
    return json.loads(resp.read().decode("utf-8"))


class ACRCloudConnector(BaseConnector):

    def authenticate(self) -> bool:
        return self.health_check()

    def health_check(self) -> bool:
        if not ACRCLOUD_ACCESS_KEY or not ACRCLOUD_SECRET:
            print("[acrcloud] Missing credentials.")
            return False
        # No lightweight health check endpoint — just verify creds exist
        return True

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "acrcloud_identify_file",
                "description": "Identify a song from an audio file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type":        "string",
                            "description": "Path to an audio file (mp3, wav, etc.)"
                        }
                    },
                    "required": ["file_path"]
                }
            },
            {
                "name":        "acrcloud_identify_microphone",
                "description": "Listen to audio from the microphone and identify the song playing.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type":        "integer",
                            "description": f"How many seconds to listen (default {RECORD_SECONDS})"
                        }
                    },
                    "required": []
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "acrcloud_identify_file":       self._identify_file,
            "acrcloud_identify_microphone": self._identify_microphone,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[acrcloud] Unknown tool: {tool_name}")
        return fn(**parameters)

    def _identify_file(self, file_path: str) -> dict:
        """Identify a song from a local audio file."""
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        return self._parse_result(_identify_audio(audio_bytes))

    def _identify_microphone(self, seconds: int = RECORD_SECONDS) -> dict:
        """
        Record from microphone and identify.
        Requires pyaudio: pip install pyaudio
        """
        try:
            import pyaudio
            import wave
            import io
        except ImportError:
            return {
                "error": "pyaudio not installed. Run: pip install pyaudio",
                "success": False,
            }

        print(f"[acrcloud] Listening for {seconds} seconds...")

        pa     = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            input=True,
            frames_per_buffer=1024,
        )

        frames = []
        for _ in range(0, int(44100 / 1024 * seconds)):
            frames.append(stream.read(1024))

        stream.stop_stream()
        stream.close()
        pa.terminate()

        # Convert to WAV bytes in memory
        buf = io.BytesIO()
        wf  = wave.open(buf, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)
        wf.writeframes(b"".join(frames))
        wf.close()

        audio_bytes = buf.getvalue()
        return self._parse_result(_identify_audio(audio_bytes))

    def _parse_result(self, raw: dict) -> dict:
        """
        Parse ACRCloud response into a clean result.
        ACRCloud returns a nested structure — we flatten the useful parts.
        """
        status = raw.get("status", {})
        code   = status.get("code", -1)

        if code != 0:
            return {
                "success":  False,
                "error":    status.get("msg", "Unknown error"),
                "code":     code,
            }

        metadata = raw.get("metadata", {})
        music    = metadata.get("music", [])

        if not music:
            return {"success": False, "error": "No match found"}

        track = music[0]

        return {
            "success":    True,
            "title":      track.get("title"),
            "artist":     ", ".join(a["name"] for a in track.get("artists", [])),
            "album":      track.get("album", {}).get("name"),
            "release":    track.get("release_date"),
            "genres":     [g["name"] for g in track.get("genres", [])],
            "score":      track.get("score"),
            "identified_at": datetime.utcnow().isoformat(),
            "external_ids": track.get("external_ids", {}),  # Spotify/ISRC IDs
        }
