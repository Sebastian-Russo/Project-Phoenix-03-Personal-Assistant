"""
Jira connector — read issues, search, get sprint data.
Uses Atlassian API token auth — same token covers Jira and Confluence.
Think of it as a badge that gets you into both buildings on the same campus.

Requires in .env:
    ATLASSIAN_EMAIL         (your Atlassian account email)
    ATLASSIAN_API_TOKEN     (generated at id.atlassian.com/manage-profile/security/api-tokens)
    ATLASSIAN_DOMAIN        (your domain, e.g. 'mycompany' from mycompany.atlassian.net)

Generate token at:
    id.atlassian.com → Security → API tokens → Create API token
"""

import os
from typing import Any

import requests

from src.connectors.base_connector import BaseConnector


class JiraConnector(BaseConnector):

    def __init__(self):
        self._email  = os.getenv("ATLASSIAN_EMAIL")
        self._token  = os.getenv("ATLASSIAN_API_TOKEN")
        self._domain = os.getenv("ATLASSIAN_DOMAIN")
        self._base   = f"https://{self._domain}.atlassian.net/rest/api/3"
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
            print("[jira] Missing credentials.")
            return False
        try:
            self._get("/myself")
            return True
        except Exception as e:
            print(f"[jira] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "jira_get_my_issues",
                "description": "Get Jira issues assigned to you.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type":        "string",
                            "description": "Filter by status (e.g. 'In Progress', 'To Do', 'Done'). Omit for all."
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max issues to return (default 10)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name":        "jira_search",
                "description": "Search Jira issues using JQL (Jira Query Language).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "jql": {
                            "type":        "string",
                            "description": "JQL query string (e.g. 'project = PHOENIX AND status = \"In Progress\"')"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max results (default 10)"
                        }
                    },
                    "required": ["jql"]
                }
            },
            {
                "name":        "jira_get_issue",
                "description": "Get details of a specific Jira issue by key.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "issue_key": {
                            "type":        "string",
                            "description": "Issue key (e.g. 'PROJ-123')"
                        }
                    },
                    "required": ["issue_key"]
                }
            },
            {
                "name":        "jira_get_sprint",
                "description": "Get issues in the current active sprint for a project.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_key": {
                            "type":        "string",
                            "description": "Project key (e.g. 'PHOENIX')"
                        }
                    },
                    "required": ["project_key"]
                }
            },
            {
                "name":        "jira_list_projects",
                "description": "List all Jira projects you have access to.",
                "input_schema": {
                    "type":       "object",
                    "properties": {},
                    "required":   []
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "jira_get_my_issues": self._get_my_issues,
            "jira_search":        self._search,
            "jira_get_issue":     self._get_issue,
            "jira_get_sprint":    self._get_sprint,
            "jira_list_projects": self._list_projects,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[jira] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _get_my_issues(self, status: str = None, limit: int = 10) -> list[dict]:
        jql = "assignee = currentUser()"
        if status:
            jql += f' AND status = "{status}"'
        jql += " ORDER BY updated DESC"
        return self._search(jql, limit)

    def _search(self, jql: str, limit: int = 10) -> list[dict]:
        data = self._get("/search", {
            "jql":        jql,
            "maxResults": limit,
            "fields":     "summary,status,assignee,priority,created,updated,issuetype",
        })
        return [
            {
                "key":      i["key"],
                "title":    i["fields"]["summary"],
                "status":   i["fields"]["status"]["name"],
                "type":     i["fields"]["issuetype"]["name"],
                "priority": i["fields"].get("priority", {}).get("name", "None"),
                "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned"),
                "updated":  i["fields"]["updated"],
                "url":      f"https://{self._domain}.atlassian.net/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ]

    def _get_issue(self, issue_key: str) -> dict:
        data   = self._get(f"/issue/{issue_key}")
        fields = data["fields"]
        return {
            "key":         data["key"],
            "title":       fields["summary"],
            "description": _extract_text(fields.get("description")),
            "status":      fields["status"]["name"],
            "type":        fields["issuetype"]["name"],
            "priority":    fields.get("priority", {}).get("name", "None"),
            "assignee":    (fields.get("assignee") or {}).get("displayName", "Unassigned"),
            "reporter":    (fields.get("reporter") or {}).get("displayName", "Unknown"),
            "created":     fields["created"],
            "updated":     fields["updated"],
            "url":         f"https://{self._domain}.atlassian.net/browse/{data['key']}",
        }

    def _get_sprint(self, project_key: str) -> list[dict]:
        """Get issues in the active sprint for a project."""
        jql = (
            f"project = {project_key} "
            f"AND sprint in openSprints() "
            f"ORDER BY status ASC"
        )
        return self._search(jql, limit=50)

    def _list_projects(self) -> list[dict]:
        data = self._get("/project")
        return [
            {
                "key":  p["key"],
                "name": p["name"],
                "type": p["projectTypeKey"],
            }
            for p in data
        ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(description: Any) -> str:
    """
    Jira descriptions use Atlassian Document Format (ADF) — a nested JSON
    structure. This recursively extracts plain text from it.
    """
    if not description:
        return ""
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        if description.get("type") == "text":
            return description.get("text", "")
        return " ".join(
            _extract_text(child)
            for child in description.get("content", [])
        )
    if isinstance(description, list):
        return " ".join(_extract_text(item) for item in description)
    return ""
