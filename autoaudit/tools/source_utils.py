from __future__ import annotations

from pathlib import Path


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

        if not lines:
            return ""

        line = max(1, line)

        start = max(0, line - context - 1)
        end = min(len(lines), line + context)

        snippet = []

        for i in range(start, end):
            prefix = ">>" if (i + 1) == line else "  "
            snippet.append(f"{prefix} {i+1}: {lines[i].rstrip()}")

        return "\n".join(snippet)

    except Exception:
        return ""