from __future__ import annotations

from autoaudit.agents.supervisor import Supervisor


def test_supervisor_full_pipeline_first_run(tmp_config, mock_repo_path):
    supervisor = Supervisor(tmp_config)
    report = supervisor.run(mock_repo_path)

    assert report.is_first_run is True
    assert report.files_scanned >= 2
    assert report.chunks_indexed > 0
    assert report.findings
    security_findings = [f for f in report.findings if f.source_agent == "security"]
    quality_findings = [f for f in report.findings if f.source_agent == "quality"]
    assert security_findings
    assert quality_findings


def test_supervisor_second_run_shows_recurring(tmp_config, mock_repo_path):
    supervisor = Supervisor(tmp_config)
    report1 = supervisor.run(mock_repo_path)
    assert report1.is_first_run is True

    report2 = supervisor.run(mock_repo_path)
    assert report2.is_first_run is False
    assert all(f.status == "recurring" for f in report2.findings)
    assert len(report2.findings) == len(report1.findings)


def test_supervisor_writes_trace_log(tmp_config, mock_repo_path):
    supervisor = Supervisor(tmp_config)
    supervisor.run(mock_repo_path)
    log_files = list(tmp_config.log_dir.glob("*.jsonl"))
    assert log_files
    content = log_files[0].read_text()
    assert "supervisor" in content
    assert "repository_agent" in content
    assert "security_agent" in content
    assert "quality_agent" in content
