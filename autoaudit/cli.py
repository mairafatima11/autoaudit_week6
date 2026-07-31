"""CLI entrypoint.

Usage:
    python -m autoaudit run <repo_path_or_url> [--output report.md]
"""
from __future__ import annotations

import argparse
import sys

from .agents.report_agent import ReportAgent
from .agents.supervisor import Supervisor
from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autoaudit", description="Autonomous multi-agent code review")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Audit a repository")
    run_p.add_argument("repo", help="Local path or git URL of the repository to audit")
    run_p.add_argument("--output", "-o", default="report.md", help="Path to write the Markdown report to")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        config = load_config()
        print(f"[autoaudit] mode={config.mode} target={args.repo}")
        print("[autoaudit] Supervisor -> Repository Agent -> Security Agent + Quality Agent -> Report Agent")

        supervisor = Supervisor(config)
        report = supervisor.run(args.repo)

        markdown = ReportAgent.render_markdown(report)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(markdown)

        counts = report.summary_counts()
        print(
            f"[autoaudit] done. files={report.files_scanned} chunks={report.chunks_indexed} "
            f"findings={len(report.findings)} (high={counts['high']} medium={counts['medium']} "
            f"low={counts['low']} info={counts['info']})"
        )
        print(f"[autoaudit] report written to {args.output}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
