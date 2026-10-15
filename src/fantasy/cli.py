"""Command line: serve | refresh | report | daily."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fantasy.app import FantasyApp
from fantasy.config import ConfigError, load_config
from fantasy.espn.client import EspnError
from fantasy.timeutil import local_date


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--demo", action="store_true", help="Use an invented league instead of ESPN"
    )
    parser = argparse.ArgumentParser(
        prog="fantasy",
        description="ESPN Fantasy Basketball daily snapshot and ChatGPT report",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", parents=[common], help="Open the dashboard in a browser")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")

    refresh = sub.add_parser(
        "refresh", parents=[common], help="Fetch the league and save today's snapshot"
    )
    refresh.add_argument(
        "--save-raw", type=Path, metavar="DIR", help="Also save ESPN's raw responses here"
    )

    report = sub.add_parser(
        "report", parents=[common], help="Print the daily report from the latest snapshot"
    )
    report.add_argument("--compact", action="store_true", help="Leave out the other rosters")
    report.add_argument("--out", type=Path, help="Write to this file instead of printing")

    daily = sub.add_parser(
        "daily", parents=[common], help="Refresh, then save the report (for a scheduled task)"
    )
    daily.add_argument("--compact", action="store_true")
    daily.add_argument("--out", type=Path, help="Default: data/reports/<date>.md")
    return parser


def _write(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Report written to {out}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # A Windows console without UTF-8 would otherwise fail on accented names.
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        config = load_config()
        app = FantasyApp(config, demo=args.demo)
        if args.command == "serve":
            from fantasy.web.server import serve

            serve(app, args.host, args.port, open_browser=not args.no_browser)
            return 0
        if args.command == "refresh":
            snapshot = app.refresh(save_raw=args.save_raw)
            print(
                f"Saved snapshot of {snapshot.league.name}: {len(snapshot.teams)} teams, "
                f"{len(snapshot.free_agent_ids)} free agents, "
                f"{len(snapshot.transactions)} transactions."
            )
            for warning in snapshot.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
            return 0
        if args.command == "daily":
            snapshot = app.refresh()
            text = app.report(compact=args.compact) or ""
            day = local_date(snapshot.fetched_at, config.tz).isoformat()
            _write(text, args.out or config.data_dir / "reports" / f"{day}.md")
            return 0
        text = app.report(compact=args.compact)
        if text is None:
            print("No snapshot yet: run `fantasy refresh` first.", file=sys.stderr)
            return 1
        _write(text, args.out)
        return 0
    except (ConfigError, EspnError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
