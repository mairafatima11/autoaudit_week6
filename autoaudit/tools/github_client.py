"""GitHub API integration: fetches repository metadata (stars, forks,
default branch, last commit, open issues, size) for repos audited via a
github.com URL. Public repos work without a token at GitHub's lower
unauthenticated rate limit; set GITHUB_TOKEN to raise that limit.

This is a best-effort enrichment layer — it never blocks or fails an
audit. If the source isn't a GitHub URL, or the API call fails for any
reason (rate limit, network, private repo without access), callers get
`None` and the Repository Overview page just omits GitHub-specific fields.
"""
from __future__ import annotations

import re

import requests

_GITHUB_URL_RE = re.compile(
    r"github\.com[:/]+(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$"
)

_TIMEOUT_SECONDS = 6.0


def parse_github_source(source: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL, or None if `source` isn't one."""
    match = _GITHUB_URL_RE.search(source.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def fetch_repo_metadata(source: str, token: str | None = None) -> dict | None:
    """Fetch repo + latest-commit metadata from the GitHub REST API.
    Returns None (never raises) if `source` isn't a GitHub URL or the
    request fails for any reason — this is enrichment, not a hard
    dependency of the audit pipeline."""
    parsed = parse_github_source(source)
    if parsed is None:
        return None
    owner, repo = parsed

    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        repo_resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}", headers=headers, timeout=_TIMEOUT_SECONDS
        )
        if repo_resp.status_code != 200:
            return {"error": f"GitHub API returned {repo_resp.status_code} for {owner}/{repo}"}
        data = repo_resp.json()

        last_commit_author = None
        last_commit_message = None
        last_commit_date = None
        try:
            commits_resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                headers=headers, timeout=_TIMEOUT_SECONDS,
                params={"per_page": 1, "sha": data.get("default_branch", "main")},
            )
            if commits_resp.status_code == 200 and commits_resp.json():
                commit = commits_resp.json()[0]
                commit_info = commit.get("commit", {})
                author_info = commit_info.get("author", {})
                last_commit_author = (commit.get("author") or {}).get("login") or author_info.get("name")
                last_commit_message = (commit_info.get("message") or "").splitlines()[0][:120]
                last_commit_date = author_info.get("date")
        except requests.RequestException:
            pass  # commit info is a nice-to-have; repo metadata below still stands

        return {
            "owner": data.get("owner", {}).get("login", owner),
            "name": data.get("name", repo),
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "language": data.get("language"),
            "size_kb": data.get("size"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "watchers": data.get("watchers_count"),
            "license": (data.get("license") or {}).get("spdx_id"),
            "topics": data.get("topics", []),
            "is_fork": data.get("fork", False),
            "archived": data.get("archived", False),
            "created_at": data.get("created_at"),
            "pushed_at": data.get("pushed_at"),
            "html_url": data.get("html_url"),
            "last_commit_author": last_commit_author,
            "last_commit_message": last_commit_message,
            "last_commit_date": last_commit_date,
        }
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}
