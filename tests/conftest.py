from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from autoaudit.config import Config

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MOCK_REPO = FIXTURES_DIR / "mock_repo"


@pytest.fixture()
def mock_repo_path() -> str:
    return str(MOCK_REPO)


@pytest.fixture()
def tmp_config(tmp_path: Path) -> Config:
    return Config(
        mode="mock",
        groq_api_key=None,
        gemini_api_key=None,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        long_function_line_threshold=40,
    )


@pytest.fixture()
def isolated_mock_repo(tmp_path: Path) -> str:
    """Copy the mock repo fixture into a throwaway tmp dir per test, so
    tests that mutate files (simulating a 'fix') don't affect each other."""
    dest = tmp_path / "mock_repo_copy"
    shutil.copytree(MOCK_REPO, dest)
    return str(dest)
