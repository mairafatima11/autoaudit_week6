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
# Exact package-manager-manifest filenames to include *regardless* of
# extension/skip rules below. These carry no "code" of their own, but
# `repo_profiler.profile_repository()` reads package.json/pyproject.toml/
# requirements.txt/etc. out of this same scanned file list to detect the
# package manager and framework. Before this was added, every one of these
# (pyproject.toml, requirements.txt, Pipfile, poetry.lock, uv.lock,
# Cargo.toml, ...) was silently dropped by the CODE_EXTENSIONS filter below,
# so the profiler never saw them and the Repository page always reported
# "Package manager: Not detected" no matter what repo_profiler.py itself
# was capable of recognizing. Matched by exact basename, not extension, so
# this doesn't sweep in unrelated .txt/.toml/.lock files (changelogs,
# licenses, arbitrary config) the way a blanket extension allowlist would.
MANIFEST_FILENAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-dev.txt",
    "Pipfile", "poetry.lock", "uv.lock",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json",
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


_URL_PREFIXES = ("http://", "https://", "git://", "ssh://", "git@")


def normalize_source(source: str) -> str:
    """Canonical form of a user-supplied repo source.

    A single leading space is enough to break everything downstream: with
    it, `startswith("https://")` is False, the URL is treated as a local
    filesystem path, and the run fails with "Repo path does not exist:
    <the URL>" — which looks absurd, because HTML collapses leading
    whitespace and the error banner renders a perfectly valid-looking URL.
    Trailing whitespace fails differently and just as confusingly, with git
    reporting that it can't clone a URL that reads correctly on screen.

    Also strips wrapping quotes, since a copied `"https://..."` is a common
    paste artefact.
    """
    cleaned = (source or "").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return cleaned


def looks_like_url(source: str) -> bool:
    """Whether `source` should be cloned rather than read from disk."""
    normalized = normalize_source(source)
    return normalized.startswith(_URL_PREFIXES) or normalized.endswith(".git")


def resolve_repo(source: str, workdir: Path) -> tuple[Path, bool]:
    """Return (local_path, is_temp). Clones `source` if it looks like a URL,
    otherwise treats it as a local path."""
    source = normalize_source(source)

    if not source:
        raise ValueError("No repository source given — provide a local path or a git URL.")

    if looks_like_url(source):
        dest = workdir / "cloned_repo"
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", source, str(dest)],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:  # `git` itself isn't installed
            raise RuntimeError(
                "git is not installed or not on PATH, so remote repositories can't be "
                "cloned. Install git, or point AutoAudit at a local directory instead."
            ) from exc
        except subprocess.CalledProcessError as exc:
            # Surface git's own message. Without this the user saw only a
            # bare non-zero exit status, which says nothing about whether
            # the repo is private, misspelled, or the network is down.
            detail = (exc.stderr or b"")
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"git clone failed for {source!r}: {detail.strip()[:400] or 'no error output'}"
            ) from exc
        return dest, True

    path = Path(source).expanduser().resolve()
    if not path.exists():
        # `source!r` on purpose: quoting is what makes stray whitespace or
        # quote characters visible. The unquoted version rendered as a
        # valid-looking URL and hid the actual problem.
        raise FileNotFoundError(
            f"Repo path does not exist: {source!r}. "
            "If you meant a remote repository, the URL must start with https:// "
            "(check for stray whitespace or quote characters)."
        )
    if not path.is_dir():
        raise NotADirectoryError(f"Repo source must be a directory, not a file: {source!r}")
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
    # Normalize once here too, so the URL check that decides whether to make
    # a temp workdir agrees with the one inside `resolve_repo`. These two
    # tests were subtly different (`startswith("http")` vs the full prefix
    # list), which is exactly the kind of drift that produces "it decided
    # this was a local path" bugs.
    source = normalize_source(source)
    workdir = Path(tempfile.mkdtemp(prefix="autoaudit_")) if looks_like_url(source) else None

    root, is_temp = resolve_repo(source, workdir or Path(tempfile.gettempdir()))
    records: list[FileRecord] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in CODE_EXTENSIONS and path.name not in MANIFEST_FILENAMES:
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