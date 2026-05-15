"""
Central config — loads .env and validates required credentials.
Same pattern as Phoenix 02 but extended for more services.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class Config:

    # ── Anthropic ─────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

    # ── Slack ─────────────────────────────────────────────────────────────────
    SLACK_ACCESS_TOKEN  = os.getenv("SLACK_ACCESS_TOKEN")
    SLACK_REFRESH_TOKEN = os.getenv("SLACK_REFRESH_TOKEN")
    SLACK_CLIENT_ID     = os.getenv("SLACK_CLIENT_ID")
    SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET")

    # ── Google ────────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_TOKEN_PATH    = os.getenv("GOOGLE_TOKEN_PATH", "certs/google_token.json")
    GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost")
    TIMEZONE             = os.getenv("TIMEZONE", "America/New_York")

    # ── Spotify ───────────────────────────────────────────────────────────────
    SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REDIRECT_URI  = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
    SPOTIFY_TOKEN_PATH    = os.getenv("SPOTIFY_TOKEN_PATH", "certs/spotify_token.json")

    # ── GitHub ────────────────────────────────────────────────────────────────
    GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN")
    GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

    # ── Atlassian (Jira + Confluence) ─────────────────────────────────────────
    ATLASSIAN_EMAIL     = os.getenv("ATLASSIAN_EMAIL")
    ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")
    ATLASSIAN_DOMAIN    = os.getenv("ATLASSIAN_DOMAIN")

    # ── Flask ─────────────────────────────────────────────────────────────────
    FLASK_PORT  = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    @classmethod
    def validate(cls) -> dict[str, list[str]]:
        """
        Check credentials per connector.
        Returns dict of connector → list of missing keys.
        Missing connectors are skipped at startup, not crashed.
        """
        checks = {
            "anthropic": {
                "ANTHROPIC_API_KEY": cls.ANTHROPIC_API_KEY,
            },
            "slack": {
                "SLACK_ACCESS_TOKEN": cls.SLACK_ACCESS_TOKEN,
            },
            "google": {
                "GOOGLE_CLIENT_ID":     cls.GOOGLE_CLIENT_ID,
                "GOOGLE_CLIENT_SECRET": cls.GOOGLE_CLIENT_SECRET,
            },
            "spotify": {
                "SPOTIFY_CLIENT_ID":     cls.SPOTIFY_CLIENT_ID,
                "SPOTIFY_CLIENT_SECRET": cls.SPOTIFY_CLIENT_SECRET,
            },
            "github": {
                "GITHUB_TOKEN":    cls.GITHUB_TOKEN,
                "GITHUB_USERNAME": cls.GITHUB_USERNAME,
            },
            "atlassian": {
                "ATLASSIAN_EMAIL":     cls.ATLASSIAN_EMAIL,
                "ATLASSIAN_API_TOKEN": cls.ATLASSIAN_API_TOKEN,
                "ATLASSIAN_DOMAIN":    cls.ATLASSIAN_DOMAIN,
            },
        }

        missing = {}
        for connector, creds in checks.items():
            absent = [k for k, v in creds.items() if not v]
            if absent:
                missing[connector] = absent

        return missing

    @classmethod
    def available_connectors(cls) -> list[str]:
        """Return list of connectors with complete credentials."""
        missing = cls.validate()
        all_connectors = ["anthropic", "slack", "google", "spotify", "github", "atlassian"]
        return [c for c in all_connectors if c not in missing]
