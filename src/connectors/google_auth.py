"""
Shared Google OAuth2 helper used by all Google connectors.
Stores the token at GOOGLE_TOKEN_PATH (default: certs/google_token.json).
First run opens a browser for consent; subsequent runs refresh silently.
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]

_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
_TOKEN_PATH    = Path(os.getenv("GOOGLE_TOKEN_PATH", "certs/google_token.json"))


def get_credentials() -> Credentials:
    creds = None

    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        client_config = {
            "installed": {
                "client_id":                   _CLIENT_ID,
                "client_secret":               _CLIENT_SECRET,
                "redirect_uris":               ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
                "token_uri":                   "https://oauth2.googleapis.com/token",
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)

    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(creds.to_json())

    return creds
