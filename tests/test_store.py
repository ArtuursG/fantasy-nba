import json
from datetime import date

from fantasy.models import Snapshot, from_dict, to_dict
from fantasy.store import SnapshotStore


def test_snapshot_survives_a_json_round_trip(today):
    restored = from_dict(Snapshot, json.loads(json.dumps(to_dict(today))))
    assert restored == today
    # int dict keys come back as ints, nested dataclasses as dataclasses
    assert all(isinstance(k, int) for k in restored.players)
    some = next(iter(restored.players.values()))
    assert type(some.stats.get("season", None)).__name__ in ("StatLine", "NoneType")


def test_old_snapshot_without_new_fields_still_loads(today):
    data = to_dict(today)
    del data["warnings"]
    for player in data["players"].values():
        del player["waiver_clear_estimated"]
    restored = from_dict(Snapshot, json.loads(json.dumps(data)))
    assert restored.warnings == []


def test_store_finds_yesterday_and_last_week(tmp_path, snapshots):
    week, yesterday, today = snapshots
    store = SnapshotStore(tmp_path / "db" / "fantasy.db")
    store.save(week, date(2026, 10, 8))
    store.save(yesterday, date(2026, 10, 14))
    store.save(today, date(2026, 10, 15))
    store.save(today, date(2026, 10, 15))  # a second refresh the same day

    assert store.count() == 4
    assert store.latest().fetched_at == today.fetched_at
    assert store.latest_before(today, date(2026, 10, 15)).fetched_at == yesterday.fetched_at
    assert store.on_or_before(today, date(2026, 10, 8)).fetched_at == week.fetched_at
    assert store.on_or_before(today, date(2026, 10, 1)) is None

    store.clear()
    assert store.latest() is None


def test_earlier_days_keep_only_their_last_snapshot(tmp_path, snapshots):
    week, yesterday, today = snapshots
    store = SnapshotStore(tmp_path / "fantasy.db")
    store.save(yesterday, date(2026, 10, 14))
    store.save(yesterday, date(2026, 10, 14))
    store.save(today, date(2026, 10, 15))
    store.save(today, date(2026, 10, 15))
    assert store.count() == 3  # one for the 14th, both of today's
    assert store.latest_before(today, date(2026, 10, 15)).fetched_at == yesterday.fetched_at


def test_status_log_records_only_changes(tmp_path, snapshots):
    import copy

    week, yesterday, today = snapshots
    store = SnapshotStore(tmp_path / "fantasy.db")
    store.record_statuses(yesterday)
    store.record_statuses(yesterday)
    later = copy.deepcopy(today)
    pid = later.teams[0].roster[0].player_id
    later.players[pid].injury_status = "OUT"
    store.record_statuses(later)
    history = store.status_history(later.league.id, later.league.season)
    assert history[pid][0] == ("OUT", later.fetched_at)
    assert len(history[pid]) == 2
    unchanged = next(
        p
        for p, rows in history.items()
        if p != pid and today.players[p].injury_status == yesterday.players[p].injury_status
    )
    assert len(history[unchanged]) == 1
