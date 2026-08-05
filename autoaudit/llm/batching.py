"""Shared helpers for batching multiple small LLM requests into a single
call.

Both the Quality Agent and the Documentation Agent were previously issuing
one Gemini request per finding/per symbol. For any repository with more
than a handful of findings, that meant dozens-to-hundreds of tiny
back-to-back requests per audit run, which is what was exhausting the
Gemini free-tier quota (HTTP 429) even though a single ad-hoc request
against the same key/model succeeded fine.

This module builds one prompt covering several "items" at once and parses
the model's response back into one string per item, using an explicit
`###ITEM <n>###` marker format so parsing doesn't depend on the model
following a particular list style.

If the model doesn't return the expected number of sections (e.g. it
merges two items, or adds commentary), `split_batch_response` returns
`None` rather than guessing — callers fall back to phrasing that batch
one item at a time so no finding/suggestion is ever silently dropped.
"""
from __future__ import annotations

import re

_ITEM_MARKER_RE = re.compile(r"#{2,3}\s*ITEM\s+(\d+)\s*#{2,3}", re.IGNORECASE)

# Batches are capped by total prompt size as well as item count. Counting
# items alone is not enough: a Quality summary is one line, but a
# Documentation prompt embeds the function's source, so eight of those can
# be tens of thousands of characters. Oversized prompts are slow to
# generate against, likelier to hit the output-token ceiling before all
# sections are written, and likelier to come back in a shape that won't
# split — which then triggers the per-item fallback and costs *more*
# requests than batching saved.
DEFAULT_MAX_BATCH_CHARS = 12_000


def chunk_items(
    items: list,
    max_items: int,
    max_chars: int = DEFAULT_MAX_BATCH_CHARS,
    size_of=len,
) -> list[list]:
    """Split `items` into batches of at most `max_items`, and at most
    roughly `max_chars` of combined prompt text.

    `size_of` extracts the prompt length from each item, so callers can pass
    richer objects (e.g. a pending finding) rather than bare strings and
    still get size-aware batching.

    An item larger than `max_chars` on its own still gets its own batch —
    better to send one oversized request than to drop the item.
    """
    batches: list[list] = []
    current: list = []
    current_chars = 0

    for item in items:
        size = size_of(item)
        if current and (len(current) >= max_items or current_chars + size > max_chars):
            batches.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += size

    if current:
        batches.append(current)
    return batches


def build_batch_prompt(items: list[str], instructions: str) -> str:
    """Combine several independent item prompts into one batched prompt.

    `instructions` is the shared task description (what to do with each
    item); `items` are the individual per-item inputs (e.g. one heuristic
    summary or one "write a docstring for ..." prompt each).
    """
    lines = [instructions, ""]
    for i, item in enumerate(items, start=1):
        lines.append(f"###ITEM {i}###")
        lines.append(item.strip())
        lines.append("")
    lines.append(
        f"Respond with exactly {len(items)} sections, one per item above, in "
        f"order. Each section must start on its own line with exactly "
        f"'###ITEM <n>###' (matching the item number) and contain only your "
        f"answer for that item — no preamble, no extra commentary, no markdown "
        f"code fences around the marker."
    )
    return "\n".join(lines)


def split_batch_response(response: str, expected_count: int) -> list[str] | None:
    """Parse a batched response back into `expected_count` strings, in item
    order. Returns None if the response doesn't cleanly contain exactly
    `expected_count` numbered sections, so the caller can fall back to
    per-item requests instead of silently misattributing text."""
    if not response or not response.strip():
        return None

    matches = list(_ITEM_MARKER_RE.finditer(response))
    if len(matches) != expected_count:
        return None

    sections: dict[int, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(response)
        try:
            item_no = int(match.group(1))
        except ValueError:
            return None
        sections[item_no] = response[start:end].strip()

    if set(sections.keys()) != set(range(1, expected_count + 1)):
        return None

    return [sections[i] for i in range(1, expected_count + 1)]