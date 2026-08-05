from __future__ import annotations

from autoaudit.tools.repo_profiler import profile_repository
from autoaudit.tools.repo_reader import FileRecord


def _rec(path: str, content: str = "", language: str = "python") -> FileRecord:
    return FileRecord(path=path, content=content, language=language, chunks=[])


def test_profile_empty_file_list():
    profile = profile_repository([])
    assert profile.total_files == 0
    assert profile.total_directories == 0
    assert profile.package_manager is None
    assert profile.frameworks == []


def test_profile_counts_files_and_directories():
    files = [
        _rec("src/app.py"),
        _rec("src/utils.py"),
        _rec("src/sub/deep.py"),
        _rec("README.md", language="markdown"),
    ]
    profile = profile_repository(files)
    assert profile.total_files == 4
    # directories: "src", "src/sub" -> 2 (root-level README.md contributes no directory)
    assert profile.total_directories == 2


def test_profile_detects_npm_via_lockfile():
    files = [_rec("package.json", content="{}", language="json"), _rec("package-lock.json", content="{}", language="json")]
    profile = profile_repository(files)
    assert profile.package_manager == "npm"


def test_profile_detects_pip_via_requirements_txt():
    files = [_rec("requirements.txt", content="fastapi\npydantic\n", language="text")]
    profile = profile_repository(files)
    assert profile.package_manager == "pip"


def test_profile_lockfile_takes_priority_over_requirements_txt():
    files = [
        _rec("requirements.txt", content="", language="text"),
        _rec("poetry.lock", content="", language="text"),
    ]
    profile = profile_repository(files)
    assert profile.package_manager == "poetry"


def test_profile_detects_react_from_package_json_dependencies():
    files = [_rec("package.json", content='{"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}', language="json")]
    profile = profile_repository(files)
    assert "React" in profile.frameworks


def test_profile_detects_fastapi_from_requirements():
    files = [_rec("requirements.txt", content="fastapi>=0.110\nuvicorn\n", language="text")]
    profile = profile_repository(files)
    assert "FastAPI" in profile.frameworks


def test_profile_detects_django_from_manage_py_even_without_dependency_file():
    files = [_rec("manage.py", content="#!/usr/bin/env python", language="python")]
    profile = profile_repository(files)
    assert "Django" in profile.frameworks


def test_profile_does_not_invent_frameworks_with_no_evidence():
    files = [_rec("src/app.py", content="print('hello')")]
    profile = profile_repository(files)
    assert profile.frameworks == []
    assert profile.package_manager is None


def test_profile_primary_language_is_majority_language():
    files = [_rec("a.py"), _rec("b.py"), _rec("c.py"), _rec("d.md", language="markdown")]
    profile = profile_repository(files)
    assert profile.primary_language == "python"
    assert profile.languages["python"] == 3
