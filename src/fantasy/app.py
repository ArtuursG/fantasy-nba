"""Refresh, history and report: what the CLI and the web page both call."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fantasy.analysis.view import build_view
from fantasy.config import Config, ConfigError
from fantasy.demo import MY_TEAM, DemoWorld
from fantasy.espn.client import EspnClient, fetch_bundle
from fantasy.espn.parse import parse_bundle
from fantasy.models import Snapshot
from fantasy.report import render_report
from fantasy.store import SnapshotStore
from fantasy.timeutil import local_date


class FantasyApp:
    def __init__(self, config: Config, demo: bool = False) -> None:
        self.config = config
        self.demo = demo
        self.store = SnapshotStore(config.db_path(demo))
        self._lock = threading.Lock()
        self._cache: tuple[str, dict] | None = None

    def refresh(self, save_raw: Path | None = None, log: Callable[[str], None] = print) -> Snapshot:
        with self._lock:
            snapshot = self._refresh_demo(log) if self.demo else self._refresh_live(save_raw, log)
            self.store.save(snapshot, local_date(snapshot.fetched_at, self.config.tz))
            self._cache = None
            return snapshot

    def _refresh_live(self, save_raw: Path | None, log: Callable[[str], None]) -> Snapshot:
        config = self.config
        if not config.league_id:
            raise ConfigError(
                "ESPN_LEAGUE_ID is not set. Put it in .dev.vars (see .dev.vars.example), "
                "or run with --demo to try the app on an invented league."
            )
        client = EspnClient(config.league_id, config.season, config.espn_s2, config.swid)
        try:
            raw = fetch_bundle(
                client,
                gamelog_days=config.gamelog_days,
                fa_pool=config.fa_pool,
                log=lambda msg: log(f"Fetching {msg}..."),
            )
        finally:
            client.close()
        if save_raw:
            save_raw.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = save_raw / f"espn-{stamp}.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            log(f"Raw ESPN responses saved to {path}")
        return parse_bundle(raw, config.team)

    def _refresh_demo(self, log: Callable[[str], None]) -> Snapshot:
        """A fresh invented league each time, with a week-old and a
        day-old snapshot behind it so the history sections have data."""
        log("Building the demo league...")
        now = datetime.now(UTC)
        world = DemoWorld(now)
        self.store.clear()
        for days in (7, 1):
            earlier = parse_bundle(world.bundle(now - timedelta(days=days)), MY_TEAM, demo=True)
            self.store.save(earlier, local_date(earlier.fetched_at, self.config.tz))
        return parse_bundle(world.bundle(now), MY_TEAM, demo=True)

    def view(self) -> dict | None:
        snapshot = self.store.latest()
        if snapshot is None:
            return None
        if self._cache and self._cache[0] == snapshot.fetched_at:
            return self._cache[1]
        day = local_date(snapshot.fetched_at, self.config.tz)
        view = build_view(
            snapshot,
            self.store.latest_before(snapshot, day),
            self.store.on_or_before(snapshot, day - timedelta(days=7)),
            self.config.tz,
        )
        self._cache = (snapshot.fetched_at, view)
        return view

    def report(self, compact: bool = False) -> str | None:
        view = self.view()
        return render_report(view, compact=compact) if view else None
