from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config import Config
from ...tools.github_client import fetch_repo_metadata
from ..dependencies import get_config

router = APIRouter(prefix="/api/repository", tags=["repository"])


@router.get("/metadata")
def get_repository_metadata(source: str, config: Config = Depends(get_config)):
    """Best-effort GitHub metadata for `source` — usable before an audit
    even starts (Repository Overview page), not tied to any run_id. Returns
    {"available": false} for non-GitHub sources rather than a 404, since
    "not a GitHub repo" isn't an error condition."""
    metadata = fetch_repo_metadata(source, token=config.github_token)
    if metadata is None:
        return {"available": False, "reason": "not_a_github_url"}
    if "error" in metadata:
        return {"available": False, "reason": metadata["error"]}
    return {"available": True, **metadata}
