"""Snapshot history in SQLite: one row per refresh, the whole normalised
snapshot as compressed JSON, so any two days can be compared later."""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from fantasy.models import Snapshot, from_dict, to_dict

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    league_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    payload BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_by_date ON snapshots (league_id, season, local_date);
-- My matchup's forecast at each refresh: one row per category, and cat '*'
-- for the chance of winning the matchup.
CREATE TABLE IF NOT EXISTS forecasts (
    fetched_at TEXT NOT NULL,
    league_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    period INTEGER NOT NULL,
    cat TEXT NOT NULL,
    p_win REAL NOT NULL,
    PRIMARY KEY (fetched_at, league_id, season, cat)
);
-- Final results of my finished matchups (WIN / LOSS / TIE), cat '*' for
-- the matchup itself.
CREATE TABLE IF NOT EXISTS results (
    league_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    period INTEGER NOT NULL,
    cat TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (league_id, season, period, cat)
);
"""


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:  # commits, or rolls back on error
                yield db
        finally:
            db.close()

    def save(self, snapshot: Snapshot, local_day: date) -> int:
        payload = zlib.compress(json.dumps(to_dict(snapshot)).encode("utf-8"))
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO snapshots (fetched_at, local_date, league_id, season, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.fetched_at,
                    local_day.isoformat(),
                    snapshot.league.id,
                    snapshot.league.season,
                    payload,
                ),
            )
            return int(cursor.lastrowid or 0)

    def _one(self, where: str, args: tuple[object, ...]) -> Snapshot | None:
        with self._connect() as db:
            row = db.execute(
                f"SELECT payload FROM snapshots WHERE {where} ORDER BY fetched_at DESC, id DESC "
                "LIMIT 1",
                args,
            ).fetchone()
        if row is None:
            return None
        return from_dict(Snapshot, json.loads(zlib.decompress(row[0]).decode("utf-8")))

    def latest(self) -> Snapshot | None:
        return self._one("1 = 1", ())

    def latest_before(self, snapshot: Snapshot, local_day: date) -> Snapshot | None:
        """The last snapshot of an earlier day for the same league, so several
        refreshes in one day all compare against yesterday."""
        return self._one(
            "league_id = ? AND season = ? AND local_date < ?",
            (snapshot.league.id, snapshot.league.season, local_day.isoformat()),
        )

    def on_or_before(self, snapshot: Snapshot, local_day: date) -> Snapshot | None:
        return self._one(
            "league_id = ? AND season = ? AND local_date <= ?",
            (snapshot.league.id, snapshot.league.season, local_day.isoformat()),
        )

    def clear(self) -> None:
        with self._connect() as db:
            for table in ("snapshots", "forecasts", "results"):
                db.execute(f"DELETE FROM {table}")

    def record_forecast(self, snapshot: Snapshot, period: int, odds: dict[str, float]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        snapshot.fetched_at,
                        snapshot.league.id,
                        snapshot.league.season,
                        period,
                        cat,
                        p,
                    )
                    for cat, p in odds.items()
                ],
            )

    def record_results(self, snapshot: Snapshot) -> int:
        """Store my finished matchups' category results found in a snapshot."""
        rows = []
        for matchup in snapshot.matchups:
            if matchup.period >= snapshot.league.matchup_period or matchup.away is None:
                continue
            if snapshot.my_team_id == matchup.home.team_id:
                side, won = matchup.home, {"HOME": "WIN", "AWAY": "LOSS"}
            elif snapshot.my_team_id == matchup.away.team_id:
                side, won = matchup.away, {"AWAY": "WIN", "HOME": "LOSS"}
            else:
                continue
            if matchup.winner == "UNDECIDED" or not side.results:
                continue
            for cat, result in side.results.items():
                rows.append((matchup.period, cat, result))
            rows.append((matchup.period, "*", won.get(matchup.winner, "TIE")))
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?, ?)",
                [(snapshot.league.id, snapshot.league.season, *row) for row in rows],
            )
        return len(rows)

    def forecast_history(
        self, league_id: int, season: int
    ) -> tuple[list[tuple[str, int, str, float]], dict[tuple[int, str], str]]:
        """(forecasts as (fetched_at, period, cat, p_win), results by (period, cat))."""
        with self._connect() as db:
            forecasts = db.execute(
                "SELECT fetched_at, period, cat, p_win FROM forecasts "
                "WHERE league_id = ? AND season = ? ORDER BY fetched_at",
                (league_id, season),
            ).fetchall()
            results = db.execute(
                "SELECT period, cat, result FROM results WHERE league_id = ? AND season = ?",
                (league_id, season),
            ).fetchall()
        return forecasts, {(period, cat): result for period, cat, result in results}

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
