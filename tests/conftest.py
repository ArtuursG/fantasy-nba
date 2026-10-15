from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fantasy.analysis.context import Context
from fantasy.analysis.view import build_view
from fantasy.demo import MY_TEAM, DemoWorld
from fantasy.espn.parse import parse_bundle

# Thursday noon US Eastern: today's games haven't tipped off yet.
NOW = datetime(2026, 10, 15, 16, 0, tzinfo=UTC)
RIGA = ZoneInfo("Europe/Riga")


@pytest.fixture(scope="session")
def world() -> DemoWorld:
    return DemoWorld(NOW)


@pytest.fixture(scope="session")
def raw_today(world):
    return world.bundle(NOW)


@pytest.fixture(scope="session")
def snapshots(world, raw_today):
    week = parse_bundle(world.bundle(NOW - timedelta(days=7)), MY_TEAM, demo=True)
    yesterday = parse_bundle(world.bundle(NOW - timedelta(days=1)), MY_TEAM, demo=True)
    today = parse_bundle(raw_today, MY_TEAM, demo=True)
    return week, yesterday, today


@pytest.fixture(scope="session")
def today(snapshots):
    return snapshots[2]


@pytest.fixture(scope="session")
def ctx(today):
    return Context.build(today)


@pytest.fixture(scope="session")
def view(snapshots):
    week, yesterday, today = snapshots
    return build_view(today, yesterday, week, RIGA)


def player_named(snapshot, name):
    return next(p for p in snapshot.players.values() if p.name == name)
