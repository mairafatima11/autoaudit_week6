"""Test-coverage signal derived from the repository's own files.

This replaces the constant `test_coverage = 70` the health score used to
emit. That constant was a placeholder: it was identical for a repo with an
exhaustive suite and a repo with no tests at all, yet carried 10% of the
composite score — so it added nothing but noise and made the overall number
look like it measured something it didn't.

We deliberately do **not** claim to measure executed line coverage — that
needs the test suite actually run under a coverage tool, which an auditor
pointed at an arbitrary untrusted repo can't safely do. Instead we measure
two things that are directly observable from source and that correlate with
whether a codebase is tested at all:

  1. **Module coverage** — the share of source modules that have a matching
     test file (``test_<name>.py`` / ``<name>_test.py`` / ``<name>.test.ts``)
     or are imported by name somewhere in the test suite.
  2. **Test density** — the ratio of test cases to source functions/classes.

Both are reported alongside the score so the UI can label it honestly as a
heuristic signal rather than passing it off as real coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..tools.repo_reader import FileRecord

# Path segments / filename patterns that mark a file as part of the test suite.
_TEST_DIR_PARTS = {"tests", "test", "__tests__", "spec", "specs", "testing"}
_TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+|[^/]+_test|conftest|[^/]+\.(test|spec))\.[A-Za-z]+$"
)
# Test case declarations across the languages the repo reader understands.
_TEST_CASE_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+test\w*|"          # pytest / unittest
    r"^\s*(?:it|test|describe)\s*\(|"            # jest / vitest / mocha
    r"^\s*func\s+Test\w+\s*\(|"                  # go
    r"^\s*@Test\b",                              # junit
    re.MULTILINE,
)
_SOURCE_SYMBOL_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(?!test)\w+|"
    r"^\s*class\s+\w+|"
    r"^\s*func\s+(?!Test)\w+\s*\(|"
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+\w+",
    re.MULTILINE,
)
# Non-source languages that shouldn't count against test coverage — a repo
# isn't "untested" because its YAML config has no unit test.
_NON_SOURCE_LANGUAGES = {"json", "yaml", "text", "shell"}


@dataclass
class TestCoverageSignal:
    """Observable test signals for one repository scan."""

    # Not a pytest test class despite the name — silences collection warnings
    # when this is imported into a test module.
    __test__ = False

    score: int = 0                  # 0-100 composite of the two ratios below
    source_files: int = 0
    test_files: int = 0
    test_cases: int = 0
    source_symbols: int = 0
    modules_with_tests: int = 0
    measured: bool = False          # False when there's no source to judge

    @property
    def module_coverage_pct(self) -> int:
        if not self.source_files:
            return 0
        return round(100 * self.modules_with_tests / self.source_files)


def signal_from_detail(detail) -> TestCoverageSignal | None:
    """Rebuild a `TestCoverageSignal` from an `AuditReport.test_coverage`
    record, so the health score can be recomputed from a report without
    needing the original `FileRecord` list (which only exists in memory
    while the run's process is alive).

    Returns None for reports predating this field, letting the caller drop
    the test category from the composite instead of scoring it 0."""
    if detail is None:
        return None
    if not getattr(detail, "measured", False) and not getattr(detail, "source_files", 0):
        return None
    return TestCoverageSignal(
        score=detail.score,
        source_files=detail.source_files,
        test_files=detail.test_files,
        test_cases=detail.test_cases,
        source_symbols=detail.source_symbols,
        modules_with_tests=detail.modules_with_tests,
        measured=detail.measured,
    )


def _is_test_file(path: str) -> bool:
    parts = path.split("/")
    if any(part.lower() in _TEST_DIR_PARTS for part in parts[:-1]):
        return True
    return bool(_TEST_FILE_RE.search(path))


def _module_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def analyze_test_coverage(files: list[FileRecord]) -> TestCoverageSignal:
    test_files = [f for f in files if _is_test_file(f.path)]
    source_files = [
        f for f in files
        if not _is_test_file(f.path)
        and f.language not in _NON_SOURCE_LANGUAGES
        and _module_name(f.path) not in ("__init__", "setup")
    ]

    if not source_files:
        # Nothing to be tested — report "not measured" rather than 0, so the
        # UI can say so instead of showing a failing grade for, say, a
        # docs-only repository.
        return TestCoverageSignal(
            score=0, source_files=0, test_files=len(test_files), measured=False
        )

    test_blob = "\n".join(f.content for f in test_files)
    test_basenames = {_module_name(f.path).lower() for f in test_files}

    test_cases = len(_TEST_CASE_RE.findall(test_blob))
    source_symbols = sum(len(_SOURCE_SYMBOL_RE.findall(f.content)) for f in source_files)

    modules_with_tests = 0
    for f in source_files:
        module = _module_name(f.path)
        lowered = module.lower()
        has_named_test = any(
            candidate in test_basenames
            for candidate in (f"test_{lowered}", f"{lowered}_test", f"{lowered}.test", f"{lowered}.spec")
        )
        # `\b` around the module name so "auth" doesn't match "authorize".
        referenced = bool(test_blob) and re.search(rf"\b{re.escape(module)}\b", test_blob) is not None
        if has_named_test or referenced:
            modules_with_tests += 1

    module_ratio = modules_with_tests / len(source_files)
    # One test case per two source symbols is treated as a well-tested
    # codebase (ratio 0.5 -> full marks on this half of the score).
    density_ratio = min(1.0, (test_cases / max(source_symbols, 1)) / 0.5)

    score = round(100 * (0.6 * module_ratio + 0.4 * density_ratio))
    return TestCoverageSignal(
        score=max(0, min(100, score)),
        source_files=len(source_files),
        test_files=len(test_files),
        test_cases=test_cases,
        source_symbols=source_symbols,
        modules_with_tests=modules_with_tests,
        measured=True,
    )
