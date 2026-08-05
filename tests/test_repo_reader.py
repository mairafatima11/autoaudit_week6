from __future__ import annotations

from autoaudit.tools import repo_reader


def test_read_repo_finds_expected_files(mock_repo_path):
    records, root, temp_dir = repo_reader.read_repo(mock_repo_path)
    paths = {r.path for r in records}
    assert "src/app.py" in paths
    assert "src/utils.py" in paths
    assert temp_dir is None 
    assert root.exists()


def test_chunking_splits_on_function_boundaries(mock_repo_path):
    records, _, _ = repo_reader.read_repo(mock_repo_path)
    app = next(r for r in records if r.path == "src/app.py")
    chunk_signatures = [c.text.lstrip().split("\n")[0] for c in app.chunks]
    assert any(sig.startswith("def get_user") for sig in chunk_signatures)
    assert any(sig.startswith("def risky_eval") for sig in chunk_signatures)


def test_long_function_chunk_has_many_lines(mock_repo_path):
    records, _, _ = repo_reader.read_repo(mock_repo_path)
    app = next(r for r in records if r.path == "src/app.py")
    long_chunk = next(c for c in app.chunks if c.text.lstrip().startswith("def long_running_task"))
    assert long_chunk.text.count("\n") + 1 > 40


def test_missing_local_path_raises(tmp_path):
    missing = tmp_path / "does_not_exist"
    try:
        repo_reader.read_repo(str(missing))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_generic_chunker_handles_non_python(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("block one line a\nblock one line b\n\nblock two line a\n")
    records, _, _ = repo_reader.read_repo(str(tmp_path))
    
    f2 = tmp_path / "script.sh"
    f2.write_text("echo one\n\necho two\n")
    records, _, _ = repo_reader.read_repo(str(tmp_path))
    sh = next(r for r in records if r.path == "script.sh")
    assert len(sh.chunks) >= 2


def test_binary_and_oversized_files_are_skipped(tmp_path):
    huge = tmp_path / "big.py"
    huge.write_text("x = 1\n" * 200000)  
    records, _, _ = repo_reader.read_repo(str(tmp_path), max_file_bytes=1000)
    assert all(r.path != "big.py" for r in records)
