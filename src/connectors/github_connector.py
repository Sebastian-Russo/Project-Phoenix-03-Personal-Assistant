"""
GitHub connector — read repos, issues, PRs, and activity.
Uses a Personal Access Token (PAT) — no OAuth flow needed.
Think of it as a library card: one token, read access to everything
you own or have been granted access to.

Requires in .env:
    GITHUB_TOKEN    (Personal Access Token from github.com/settings/tokens)
    GITHUB_USERNAME (your GitHub username)

Generate token at:
    github.com → Settings → Developer Settings → Personal Access Tokens → Fine-grained
    Permissions needed: Contents (read), Issues (read), Pull Requests (read), Metadata (read)
"""

import os
from datetime import datetime
from typing import Any, Optional

import requests

from src.connectors.base_connector import BaseConnector


GITHUB_BASE_URL = "https://api.github.com"


class GitHubConnector(BaseConnector):

    def __init__(self):
        self._token    = os.getenv("GITHUB_TOKEN")
        self._username = os.getenv("GITHUB_USERNAME")
        self._session  = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Accept":        "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, path: str, params: dict = None) -> Any:
        resp = self._session.get(
            f"{GITHUB_BASE_URL}{path}",
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def authenticate(self) -> bool:
        return self.health_check()

    def health_check(self) -> bool:
        if not self._token:
            print("[github] No token configured.")
            return False
        try:
            self._get("/user")
            return True
        except Exception as e:
            print(f"[github] Health check failed: {e}")
            return False

    def get_tools(self) -> list[dict]:
        return [
            {
                "name":        "github_list_repos",
                "description": "List your GitHub repositories.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type":        "integer",
                            "description": "Max repos to return (default 20)"
                        },
                        "sort": {
                            "type":        "string",
                            "enum":        ["updated", "created", "pushed", "full_name"],
                            "description": "Sort order (default: updated)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name":        "github_get_issues",
                "description": "Get open issues for a repository.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type":        "string",
                            "description": "Repository name (e.g. 'my-project') or full path (e.g. 'username/my-project')"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max issues to return (default 10)"
                        },
                        "state": {
                            "type":        "string",
                            "enum":        ["open", "closed", "all"],
                            "description": "Issue state filter (default: open)"
                        }
                    },
                    "required": ["repo"]
                }
            },
            {
                "name":        "github_get_prs",
                "description": "Get pull requests for a repository.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type":        "string",
                            "description": "Repository name or full path"
                        },
                        "state": {
                            "type":        "string",
                            "enum":        ["open", "closed", "all"],
                            "description": "PR state filter (default: open)"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max PRs to return (default 10)"
                        }
                    },
                    "required": ["repo"]
                }
            },
            {
                "name":        "github_get_activity",
                "description": "Get recent activity and commits for a repository.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type":        "string",
                            "description": "Repository name or full path"
                        },
                        "limit": {
                            "type":        "integer",
                            "description": "Max commits to return (default 10)"
                        }
                    },
                    "required": ["repo"]
                }
            },
            {
                "name":        "github_search_issues",
                "description": "Search issues and PRs across all your repositories.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "Search query (e.g. 'bug label:critical', 'assigned to me')"
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
                "name":        "github_get_repo_summary",
                "description": "Get a summary of a repository including stats, language, and recent activity.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type":        "string",
                            "description": "Repository name or full path"
                        }
                    },
                    "required": ["repo"]
                }
            },
        ]

    def execute_tool(self, tool_name: str, parameters: dict) -> Any:
        dispatch = {
            "github_list_repos":     self._list_repos,
            "github_get_issues":     self._get_issues,
            "github_get_prs":        self._get_prs,
            "github_get_activity":   self._get_activity,
            "github_search_issues":  self._search_issues,
            "github_get_repo_summary": self._get_repo_summary,
        }
        fn = dispatch.get(tool_name)
        if not fn:
            raise ValueError(f"[github] Unknown tool: {tool_name}")
        return fn(**parameters)

    # ── Implementations ───────────────────────────────────────────────────────

    def _list_repos(self, limit: int = 20, sort: str = "updated") -> list[dict]:
        data = self._get("/user/repos", {"sort": sort, "per_page": limit})
        return [
            {
                "name":        r["name"],
                "full_name":   r["full_name"],
                "description": r["description"],
                "language":    r["language"],
                "stars":       r["stargazers_count"],
                "open_issues": r["open_issues_count"],
                "updated":     r["updated_at"],
                "url":         r["html_url"],
            }
            for r in data
        ]

    def _resolve_repo(self, repo: str) -> str:
        """Resolve short repo name to full owner/repo path."""
        if "/" in repo:
            return repo
        return f"{self._username}/{repo}"

    def _get_issues(
        self,
        repo:  str,
        limit: int = 10,
        state: str = "open",
    ) -> list[dict]:
        full = self._resolve_repo(repo)
        data = self._get(f"/repos/{full}/issues", {
            "state":    state,
            "per_page": limit,
        })
        return [
            {
                "number":  i["number"],
                "title":   i["title"],
                "state":   i["state"],
                "author":  i["user"]["login"],
                "labels":  [l["name"] for l in i["labels"]],
                "created": i["created_at"],
                "url":     i["html_url"],
                "body":    (i.get("body") or "")[:300],  # truncate long bodies
            }
            for i in data
            if "pull_request" not in i  # exclude PRs from issues list
        ]

    def _get_prs(
        self,
        repo:  str,
        state: str = "open",
        limit: int = 10,
    ) -> list[dict]:
        full = self._resolve_repo(repo)
        data = self._get(f"/repos/{full}/pulls", {
            "state":    state,
            "per_page": limit,
        })
        return [
            {
                "number":    pr["number"],
                "title":     pr["title"],
                "state":     pr["state"],
                "author":    pr["user"]["login"],
                "base":      pr["base"]["ref"],
                "head":      pr["head"]["ref"],
                "created":   pr["created_at"],
                "url":       pr["html_url"],
                "mergeable": pr.get("mergeable"),
            }
            for pr in data
        ]

    def _get_activity(self, repo: str, limit: int = 10) -> list[dict]:
        full = self._resolve_repo(repo)
        data = self._get(f"/repos/{full}/commits", {"per_page": limit})
        return [
            {
                "sha":     c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0],  # first line only
                "author":  c["commit"]["author"]["name"],
                "date":    c["commit"]["author"]["date"],
                "url":     c["html_url"],
            }
            for c in data
        ]

    def _search_issues(self, query: str, limit: int = 10) -> list[dict]:
        # Scope search to user's repos by default
        scoped_query = f"{query} user:{self._username}"
        data = self._get("/search/issues", {
            "q":        scoped_query,
            "per_page": limit,
        })
        return [
            {
                "number":  i["number"],
                "title":   i["title"],
                "state":   i["state"],
                "repo":    i["repository_url"].split("/")[-1],
                "author":  i["user"]["login"],
                "created": i["created_at"],
                "url":     i["html_url"],
            }
            for i in data.get("items", [])
        ]

    def _get_repo_summary(self, repo: str) -> dict:
        full = self._resolve_repo(repo)
        data = self._get(f"/repos/{full}")
        return {
            "name":        data["name"],
            "description": data["description"],
            "language":    data["language"],
            "stars":       data["stargazers_count"],
            "forks":       data["forks_count"],
            "open_issues": data["open_issues_count"],
            "created":     data["created_at"],
            "updated":     data["updated_at"],
            "url":         data["html_url"],
            "topics":      data.get("topics", []),
        }
