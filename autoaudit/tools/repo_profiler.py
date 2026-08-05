"""Repository profiler: infers package manager, detected frameworks, and
directory/file totals from the already-scanned file set — no extra I/O,
just pattern-matching over paths and (for the few files small enough to
matter) content already held in memory by the Repository Agent.

Deliberately conservative: a framework/package-manager is only reported
when a concrete indicator file or an exact dependency name is present —
no guessing from vague naming conventions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .repo_reader import FileRecord

# path basename -> package manager name
PACKAGE_MANAGER_INDICATORS: dict[str, str] = {
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "Pipfile": "pipenv",
    "requirements.txt": "pip",
    # Bare pyproject.toml (no lockfile above matched) still means the repo
    # is packaged with the standard PEP 517/518 pip toolchain — this was
    # previously missing entirely, which caused any pyproject.toml-only
    # Python repo (e.g. modern packages using `uv`/`hatch`/`setuptools`
    # with no requirements.txt) to report "Not detected".
    "pyproject.toml": "pip",
    "Cargo.toml": "cargo",
    "go.mod": "go modules",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "Gemfile": "bundler",
    "composer.json": "composer",
}
# Precedence when multiple indicators are present (lockfiles are more
# specific than requirements.txt, etc.)
PACKAGE_MANAGER_PRIORITY = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "uv.lock", "poetry.lock", "Pipfile", "requirements.txt", "pyproject.toml",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json",
]

# framework name -> (dependency names to look for in package.json/requirements.txt,
# characteristic file basenames)
FRAMEWORK_DEPENDENCY_HINTS: dict[str, list[str]] = {
    "React": ["react", "react-dom"],
    "Next.js": ["next"],
    "Vue": ["vue"],
    "Angular": ["@angular/core"],
    "Express": ["express"],
    "Django": ["django", "Django"],
    "Flask": ["flask", "Flask"],
    "FastAPI": ["fastapi"],
    "Ruby on Rails": ["rails"],
    "Spring": ["spring-boot-starter", "org.springframework"],
}
FRAMEWORK_FILE_HINTS: dict[str, list[str]] = {
    "Django": ["manage.py"],
    "Next.js": ["next.config.js", "next.config.ts", "next.config.mjs"],
}


@dataclass
class RepoProfile:
    total_files: int = 0
    total_directories: int = 0
    package_manager: str | None = None
    frameworks: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    primary_language: str | None = None


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def profile_repository(files: list[FileRecord]) -> RepoProfile:
    if not files:
        return RepoProfile()

    directories: set[str] = set()
    for rec in files:
        if "/" in rec.path:
            parts = rec.path.split("/")[:-1]
            for i in range(len(parts)):
                directories.add("/".join(parts[: i + 1]))

    basenames = {_basename(f.path): f for f in files}

    package_manager = None
    for indicator in PACKAGE_MANAGER_PRIORITY:
        if indicator in basenames:
            package_manager = PACKAGE_MANAGER_INDICATORS[indicator]
            break

    dependency_text = ""
    for indicator_file in ("package.json", "requirements.txt", "pyproject.toml", "Gemfile", "composer.json"):
        if indicator_file in basenames:
            dependency_text += basenames[indicator_file].content.lower() + "\n"

    frameworks: list[str] = []
    for framework, deps in FRAMEWORK_DEPENDENCY_HINTS.items():
        if any(dep.lower() in dependency_text for dep in deps):
            frameworks.append(framework)
    for framework, filenames in FRAMEWORK_FILE_HINTS.items():
        if framework not in frameworks and any(fn in basenames for fn in filenames):
            frameworks.append(framework)

    languages: dict[str, int] = {}
    for rec in files:
        languages[rec.language] = languages.get(rec.language, 0) + 1
    primary_language = max(languages, key=lambda k: languages[k]) if languages else None

    return RepoProfile(
        total_files=len(files),
        total_directories=len(directories),
        package_manager=package_manager,
        frameworks=sorted(frameworks),
        languages=languages,
        primary_language=primary_language,
    )
