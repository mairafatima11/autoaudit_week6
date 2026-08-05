from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ..tools.repo_reader import normalize_source


class AuditRequest(BaseModel):
    source: str = Field(..., description="Local path or git URL of the repository to audit")

    @field_validator("source")
    @classmethod
    def _normalize(cls, value: str) -> str:
        """Normalize at the boundary so nothing downstream ever sees a
        padded source.

        This matters beyond the immediate crash: `repo_source` is persisted
        with every run and `repo_id` is derived from it, so a source that
        differs only by a leading space would fork one repository's audit
        history into two unrelated timelines.
        """
        cleaned = normalize_source(value)
        if not cleaned:
            raise ValueError("Repository source must not be empty.")
        return cleaned


class AuditStartResponse(BaseModel):
    run_id: str
    status: str


class ModelCompareRequest(BaseModel):
    prompt: str
    system: str | None = None
    providers: list[str] | None = None


class FixRequest(BaseModel):
    max_findings: int | None = 10
    fingerprints: list[str] | None = None  # if set, only propose fixes for these findings
