"""Week 7 output validation: every structured LLM output (Fix Agent,
Documentation Agent, reconciliation) is parsed into a Pydantic schema
before it's allowed into the pipeline. Invalid output is retried, then
repaired by re-prompting the model with the validation error, then retried
on a fallback model. If nothing produces valid output, the caller gets a
clear `ValidationFailure` instead of a malformed object silently entering
the audit report.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMClient

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


class ValidationFailure(RuntimeError):
    def __init__(self, schema: Type[BaseModel], attempts: list[str]) -> None:
        self.schema = schema
        self.attempts = attempts
        super().__init__(
            f"Could not produce output matching {schema.__name__} after {len(attempts)} attempt(s)."
        )


@dataclass
class ValidatedResult:
    value: BaseModel
    attempts: int
    repaired: bool
    model_used: str


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw).rstrip("`").strip()
    match = _JSON_BLOCK_RE.search(raw)
    return match.group(0) if match else raw


def parse_and_validate(raw: str, schema: Type[T]) -> T:
    """Parse `raw` as JSON and validate against `schema`. Raises
    ValueError/ValidationError on failure (caller decides how to react)."""
    payload = json.loads(_extract_json(raw))
    return schema.model_validate(payload)


def validate_with_repair(
    schema: Type[T],
    initial_raw: str,
    *,
    primary_client: LLMClient,
    fallback_client: LLMClient | None = None,
    original_prompt: str = "",
    system: str | None = None,
    max_repair_attempts: int = 2,
) -> ValidatedResult:
    """Validate `initial_raw` against `schema`. On failure, re-prompt the
    model with the validation error asking it to repair its own output
    (schema guard). If repairs on the primary model are exhausted, fall
    back to `fallback_client` once before giving up.
    """
    attempts_log: list[str] = []
    raw = initial_raw
    client = primary_client
    repaired = False

    budget = max_repair_attempts + (1 if fallback_client else 0)

    for attempt in range(budget + 1):
        try:
            value = parse_and_validate(raw, schema)
            return ValidatedResult(
                value=value,
                attempts=attempt + 1,
                repaired=repaired,
                model_used=client.provider,
            )
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            attempts_log.append(f"{client.provider}: {exc}")
            if attempt >= budget:
                break

            # Once primary repair attempts are exhausted, switch to the
            # fallback model for the final try.
            if attempt == max_repair_attempts - 1 and fallback_client is not None:
                client = fallback_client

            repair_prompt = (
                f"Your previous response did not match the required JSON schema.\n\n"
                f"Original task:\n{original_prompt}\n\n"
                f"Your previous (invalid) response:\n{raw}\n\n"
                f"Validation error:\n{exc}\n\n"
                f"Required JSON schema:\n{json.dumps(schema.model_json_schema())}\n\n"
                f"Return ONLY corrected JSON matching the schema. No prose, no markdown fences."
            )
            raw = client.complete(repair_prompt, system=system)
            repaired = True

    raise ValidationFailure(schema, attempts_log)
