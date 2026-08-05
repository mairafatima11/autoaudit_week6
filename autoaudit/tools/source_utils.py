from __future__ import annotations

from pathlib import Path


def _render_window(lines: list[str], line: int, context: int) -> str:
    """Render a `>>`-marked window of `lines` centred on `line` (1-based)."""
    if not lines:
        return ""

    line = max(1, line)
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)

    return "\n".join(
        f"{'>>' if (i + 1) == line else '  '} {i + 1}: {lines[i].rstrip()}"
        for i in range(start, end)
    )


def extract_source_snippet_from_content(
    content: str,
    line: int,
    context: int = 3,
) -> str:
    """Same window as `extract_source_snippet`, but reading from an
    already-in-memory file body instead of from disk.

    This is the path the Fix Agent actually needs for cloned repositories:
    by the time fixes are requested, `Supervisor.run()` has already deleted
    the clone's temp directory (`cleanup_if_temp`), so `root_path` points at
    nothing and the disk-based reader returns "". Feeding the model an empty
    "Surrounding code" block is what produced ungrounded, placeholder-filled
    patches for URL-sourced repos. The Repository Agent's `FileRecord` list
    is still held in `Supervisor._run_contexts`, so the real source is
    available here without re-cloning.
    """
    if not content:
        return ""
    return _render_window(content.splitlines(), line, context)


def extract_source_snippet(
    root_path: str,
    file_path: str,
    line: int,
    context: int = 3,
) -> str:
    """
    Extract a few lines around the reported line.
    """

    try:
        full_path = Path(root_path) / file_path

        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        return _render_window(lines, line, context)

    except Exception:
        return ""