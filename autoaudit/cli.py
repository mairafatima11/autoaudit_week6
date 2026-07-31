from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoaudit",
        description="Autonomous multi-agent code review",
    )

    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Audit a repository")
    run.add_argument("repo")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        print("=" * 50)
        print("AutoAudit AI")
        print("Project scaffold initialized.")
        print(f"Target repository: {args.repo}")
        print("Audit pipeline is not implemented yet.")
        print("=" * 50)
        return 0

    parser.print_help()
    return 0