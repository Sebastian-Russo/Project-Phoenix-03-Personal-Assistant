"""
Confluence connector — read pages, search content, get space info.
Shares the same Atlassian API token as Jira — no extra setup needed.
Think of Confluence as Jira's quieter sibling: same building, different floor.

Requires in .env:
    ATLASSIAN_EMAIL
    ATLASSIAN_API_TOKEN
    ATLASSIAN_DOMAIN
"""

import os
from typing import Any

import requests

from src.connectors.base_connector import BaseConnector


class ConfluenceConnector(BaseConnector):

    def __init__(self):
        self._email  = os.getenv("ATLASSIAN_EMAIL")
        self._token  = os.getenv("ATLASSIAN_API_TOKEN")
        self._domain = os.getenv("ATLASSIAN_DOMAIN")
        self._base   = f"https://{self._domain}.atlassian.net/wiki/rest/api"
        self._session = requests.Session()
        self._session.auth    = (self._email, self._token)
        self._session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict = None) -> Any:
        resp = self._session.get(
            f"{self._base}{path}",
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def authenticate(self) -> bool:
        return self.health_check()

    def health_check(self) -> bool:
        if not all([self._email, self._token, self._domain]):
            print("[confluence] Missing credentials.")
            return False
        try:
            self._get("/space", {"limit": 1})
            return True
        except Exception as e:
            print(f"[confluence] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "confluence_search",
                "description": "Search Confluence pages by keyword or phrase.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "Search query"
                        },
                        "space_key": {
                            "type":        "string",
                            "description": "Limit search to a specific space (optional)"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max results (default 10)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name":        "confluence_get_page",
                "description": "Get the full content of a Confluence page by ID or title.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "page_id": {
                            "type":        "string",
                            "description": "Page ID (numeric) — use confluence_search to find it"
                        }
                    },
                    "required": ["page_id"]
                }
            },
            {
                "name":        "confluence_list_spaces",
                "description": "List all Confluence spaces you have access to.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
            {
                "name":        "confluence_get_space_pages",
                "description": "List recent pages in a Confluence space.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "space_key": {
                            "type":        "string",
                            "description": "Space key (e.g. 'ENGINEERING', 'PROJ')"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max pages to return (default 10)"
                        }
                    },
                    "required": ["space_key"]
                }
            },
            {
                "name":        "confluence_get_recently_updated",
                "description": "Get recently updated Confluence pages across all spaces.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type":        "integer",
                            "description": "Max pages to return (default 10)"
                        }
                    },
                    "required": []
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "confluence_search":             self._search,
            "confluence_get_page":           self._get_page,
            "confluence_list_spaces":        self._list_spaces,
            "confluence_get_space_pages":    self._get_space_pages,
            "confluence_get_recently_updated": self._get_recently_updated,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[confluence] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _search(self, query: str, space_key: str = None, limit: int = 10) -> list[dict]:
        cql = f'text ~ "{query}" AND type = page'
        if space_key:
            cql += f' AND space.key = "{space_key}"'

        data = self._get("/content/search", {
            "cql":   cql,
            "limit": limit,
        })

        return [
            {
                "id":      r["id"],
                "title":   r["title"],
                "space":   r.get("space", {}).get("key", ""),
                "url":     f"https://{self._domain}.atlassian.net/wiki{r['_links']['webui']}",
                "excerpt": r.get("excerpt", ""),
            }
            for r in data.get("results", [])
        ]

    def _get_page(self, page_id: str) -> dict:
        data = self._get(f"/content/{page_id}", {
            "expand": "body.storage,version,space"
        })

        # Strip HTML tags from body for plain text
        raw_body = data.get("body", {}).get("storage", {}).get("value", "")
        plain    = _strip_html(raw_body)

        return {
            "id":      data["id"],
            "title":   data["title"],
            "space":   data.get("space", {}).get("key", ""),
            "version": data.get("version", {}).get("number", 1),
            "body":    plain[:3000],  # truncate very long pages
            "url":     f"https://{self._domain}.atlassian.net/wiki{data['_links']['webui']}",
        }

    def _list_spaces(self) -> list[dict]:
        data = self._get("/space", {"limit": 50})
        return [
            {
                "key":  s["key"],
                "name": s["name"],
                "type": s["type"],
            }
            for s in data.get("results", [])
        ]

    def _get_space_pages(self, space_key: str, limit: int = 10) -> list[dict]:
        data = self._get("/content", {
            "spaceKey": space_key,
            "type":     "page",
            "limit":    limit,
            "orderby":  "modified desc",
        })

        return [
            {
                "id":    p["id"],
                "title": p["title"],
                "url":   f"https://{self._domain}.atlassian.net/wiki{p['_links']['webui']}",
            }
            for p in data.get("results", [])
        ]

    def _get_recently_updated(self, limit: int = 10) -> list[dict]:
        data = self._get("/content/search", {
            "cql":   "type = page ORDER BY lastModified DESC",
            "limit": limit,
        })

        return [
            {
                "id":      r["id"],
                "title":   r["title"],
                "space":   r.get("space", {}).get("key", ""),
                "url":     f"https://{self._domain}.atlassian.net/wiki{r['_links']['webui']}",
                "excerpt": r.get("excerpt", ""),
            }
            for r in data.get("results", [])
        ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """
    Remove HTML tags from Confluence storage format.
    Not a full HTML parser — just strips tags for readable plain text.
    Good enough for passing content to Claude.
    """
    import re
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
