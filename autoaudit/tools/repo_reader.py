"""Repository Agent's core tool: get a repo onto disk (or use a local path
as-is) and turn it into a list of chunked, in-memory file records.

This is the "File Reader skill extended to a full directory tree" mentioned
in the proposal.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "dist", "build"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".php",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".sh", ".yml", ".yaml", ".json",
}
BINARY_MARKERS = (b"\x00",)


@dataclass
class Chunk:
    id: str
    file: str
    start_line: int
    text: str


@dataclass
class FileRecord:
    path: str            
    content: str
    language: str
    chunks: list[Chunk] = field(default_factory=list)


def is_probably_binary(raw: bytes) -> bool:
    if not raw:
        return False
    return any(marker in raw[:4096] for marker in BINARY_MARKERS)


def language_for(path: str) -> str:
    ext = Path(path).suffix
    return {
        ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
        ".jsx": "javascript", ".go": "go", ".java": "java", ".rb": "ruby", ".php": "php",
        ".c": "c", ".cc": "cpp", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".rs": "rust",
        ".sh": "shell", ".yml": "yaml", ".yaml": "yaml", ".json": "json",
    }.get(ext, "text")


def resolve_repo(source: str, workdir: Path) -> tuple[Path, bool]:
    """Return (local_path, is_temp). Clones `source` if it looks like a URL,
    otherwise treats it as a local path."""
    if source.startswith("http://") or source.startswith("https://") or source.endswith(".git"):
        dest = workdir / "cloned_repo"
        subprocess.run(
            ["git", "clone", "--depth", "1", source, str(dest)],
            check=True,
            capture_output=True,
        )
        return dest, True
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Repo path does not exist: {source}")
    return path, False


PY_DEF_RE = re.compile(r"^(def |class |async def )", re.MULTILINE)


def chunk_python(path: str, content: str) -> list[Chunk]:
    """Split on top-level def/class boundaries."""
    lines = content.splitlines()
    boundaries = [i for i, line in enumerate(lines) if PY_DEF_RE.match(line)]
    if not boundaries:
        return [Chunk(id=f"{path}:0", file=path, start_line=1, text=content)] if content.strip() else []

    chunks: list[Chunk] = []
    if boundaries[0] > 0:
        header = "\n".join(lines[: boundaries[0]])
        if header.strip():
            chunks.append(Chunk(id=f"{path}:0", file=path, start_line=1, text=header))

    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(lines)
        text = "\n".join(lines[start:end])
        chunks.append(Chunk(id=f"{path}:{start + 1}", file=path, start_line=start + 1, text=text))
    return chunks


def chunk_generic(path: str, content: str) -> list[Chunk]:
    """Fallback: split on blank-line-delimited blocks."""
    blocks = re.split(r"\n\s*\n", content)
    chunks: list[Chunk] = []
    line_cursor = 1
    for block in blocks:
        if block.strip():
            chunks.append(Chunk(id=f"{path}:{line_cursor}", file=path, start_line=line_cursor, text=block))
        line_cursor += block.count("\n") + 1
    return chunks or ([Chunk(id=f"{path}:0", file=path, start_line=1, text=content)] if content.strip() else [])


def chunk_file(path: str, content: str, language: str) -> list[Chunk]:
    if language == "python":
        return chunk_python(path, content)
    return chunk_generic(path, content)


def read_repo(source: str, max_file_bytes: int = 400_000) -> tuple[list[FileRecord], Path, Path | None]:
    """Read every code file in `source` (local path or git URL).

    Returns (file_records, resolved_root_path, temp_dir_or_None). The repo
    is only ever cloned once here; callers needing the local root again
    (e.g. to hand to Semgrep) should reuse `resolved_root_path` rather than
    calling `resolve_repo` a second time. Caller is responsible for cleaning
    up temp_dir if it isn't None (use `cleanup_if_temp`).
    """
    workdir = Path(tempfile.mkdtemp(prefix="autoaudit_")) if (
        source.startswith("http") or source.endswith(".git")
    ) else None

    root, is_temp = resolve_repo(source, workdir or Path(tempfile.gettempdir()))
    records: list[FileRecord] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in CODE_EXTENSIONS:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > max_file_bytes or is_probably_binary(raw):
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        rel = path.relative_to(root).as_posix()
        lang = language_for(rel)
        rec = FileRecord(path=rel, content=content, language=lang)
        rec.chunks = chunk_file(rel, content, lang)
        records.append(rec)

    return records, root, (workdir if is_temp else None)


def cleanup_if_temp(temp_dir: Path | None) -> None:
    if temp_dir is not None and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
