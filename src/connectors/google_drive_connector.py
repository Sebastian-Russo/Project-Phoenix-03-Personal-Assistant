"""
Google Drive connector — upload files, create folders, search, organize.
Shares the same OAuth token as Google Calendar — one consent flow
covers both. Think of it as one key that opens multiple rooms.

Requires in .env:
    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    GOOGLE_TOKEN_PATH   (default: certs/google_token.json)
"""

import io
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from src.connectors.base_connector import BaseConnector
from src.connectors.google_auth import get_credentials


class GoogleDriveConnector(BaseConnector):

    def __init__(self):
        self._creds   = None
        self._service = None

    def authenticate(self) -> bool:
        try:
            self._creds   = get_credentials()
            self._service = build("drive", "v3", credentials=self._creds)
            return True
        except Exception as e:
            print(f"[gdrive] Authentication failed: {e}")
            return False

    def health_check(self) -> bool:
        if not self._service:
            return False
        try:
            self._service.files().list(pageSize=1).execute()
            return True
        except Exception as e:
            print(f"[gdrive] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "drive_upload_file",
                "description": "Upload a local file to Google Drive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type":        "string",
                            "description": "Local path to the file to upload"
                        },
                        "folder_id": {
                            "type":        "string",
                            "description": "Drive folder ID to upload into (optional, defaults to root)"
                        },
                        "rename": {
                            "type":        "string",
                            "description": "Override filename in Drive (optional)"
                        }
                    },
                    "required": ["file_path"]
                }
            },
            {
                "name":        "drive_create_folder",
                "description": "Create a new folder in Google Drive.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type":        "string",
                            "description": "Folder name"
                        },
                        "parent_id": {
                            "type":        "string",
                            "description": "Parent folder ID (optional, defaults to root)"
                        }
                    },
                    "required": ["name"]
                }
            },
            {
                "name":        "drive_search",
                "description": "Search for files in Google Drive by name or content.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "Search query (file name, type, or content)"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max results to return (default 10)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name":        "drive_list_folder",
                "description": "List files inside a specific Drive folder.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type":        "string",
                            "description": "Drive folder ID to list (use 'root' for root)"
                        }
                    },
                    "required": ["folder_id"]
                }
            },
            {
                "name":        "drive_upload_bytes",
                "description": "Upload raw bytes or text content directly to Drive without a local file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type":        "string",
                            "description": "Name for the file in Drive"
                        },
                        "content": {
                            "type":        "string",
                            "description": "Text content to upload"
                        },
                        "folder_id": {
                            "type":        "string",
                            "description": "Drive folder ID (optional)"
                        },
                        "mime_type": {
                            "type":        "string",
                            "description": "MIME type (default: text/plain)"
                        }
                    },
                    "required": ["filename", "content"]
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "drive_upload_file":   self._upload_file,
            "drive_create_folder": self._create_folder,
            "drive_search":        self._search,
            "drive_list_folder":   self._list_folder,
            "drive_upload_bytes":  self._upload_bytes,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[gdrive] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _upload_file(
        self,
        file_path: str,
        folder_id: str = None,
        rename:    str = None,
    ) -> dict:
        path      = Path(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        filename  = rename or path.name

        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

        try:
            file = self._service.files().create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
            ).execute()

            print(f"[gdrive] Uploaded: {filename} → {file.get('webViewLink')}")
            return {
                "id":          file["id"],
                "name":        file["name"],
                "web_link":    file.get("webViewLink"),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
        except HttpError as e:
            print(f"[gdrive] Upload failed: {e}")
            raise

    def _upload_bytes(
        self,
        filename:  str,
        content:   str,
        folder_id: str = None,
        mime_type: str = "text/plain",
    ) -> dict:
        """Upload string content directly without a local file."""
        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )

        try:
            file = self._service.files().create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
            ).execute()

            return {
                "id":       file["id"],
                "name":     file["name"],
                "web_link": file.get("webViewLink"),
            }
        except HttpError as e:
            print(f"[gdrive] Bytes upload failed: {e}")
            raise

    def _create_folder(self, name: str, parent_id: str = None) -> dict:
        metadata = {
            "name":     name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        try:
            folder = self._service.files().create(
                body=metadata,
                fields="id, name, webViewLink",
            ).execute()
            return {
                "id":      folder["id"],
                "name":    folder["name"],
                "web_link": folder.get("webViewLink"),
            }
        except HttpError as e:
            print(f"[gdrive] Create folder failed: {e}")
            raise

    def _search(self, query: str, limit: int = 10) -> list[dict]:
        try:
            result = self._service.files().list(
                q=f"name contains '{query}' and trashed=false",
                pageSize=limit,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
            ).execute()

            return [
                {
                    "id":            f["id"],
                    "name":          f["name"],
                    "type":          f["mimeType"],
                    "web_link":      f.get("webViewLink"),
                    "modified":      f.get("modifiedTime"),
                }
                for f in result.get("files", [])
            ]
        except HttpError as e:
            print(f"[gdrive] Search failed: {e}")
            return []

    def _list_folder(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and trashed=false"
        try:
            result = self._service.files().list(
                q=query,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
            ).execute()

            return [
                {
                    "id":       f["id"],
                    "name":     f["name"],
                    "type":     f["mimeType"],
                    "web_link": f.get("webViewLink"),
                    "modified": f.get("modifiedTime"),
                }
                for f in result.get("files", [])
            ]
        except HttpError as e:
            print(f"[gdrive] List folder failed: {e}")
            return []

