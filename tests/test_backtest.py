from dataclasses import replace
from datetime import date

import pytest

from fantasy.analysis.backtest import (
    MATCHUP,
    Call,
    Final,
    finals,
    forecast_league,
    projection_errors,
    render_backtest,
    run_backtest,
    score_calls,
)
from fantasy.cli import main
from fantasy.store import SnapshotStore


def _call(cat, p, edge=None, sd=0.0, days_left=6, **finals_):
    return Call("t1", 4, 1, 2, cat, p, days_left, edge, sd, **finals_)


def test_calls_are_scored_from_the_home_side():
    outcome = Final(
        results={"PTS": "WIN", "TO": "LOSS", "REB": "TIE", MATCHUP: "WIN"},
        home={"PTS": 800.0, "TO": 100.0, "REB": 300.0},
        away={"PTS": 700.0, "TO": 90.0, "REB": 300.0},
    )
    calls = [
        _call("PTS", 0.9, edge=60.0, sd=20.0, home_final=1000.0, away_final=940.0),
        _call("TO", 0.2, edge=-20.0, sd=10.0, home_final=100.0, away_final=80.0),
        _call("REB", 0.6, edge=5.0, sd=5.0, home_final=300.0, away_final=295.0),
        _call(MATCHUP, 0.7),
        Call("t1", 9, 1, 2, "PTS", 0.5, 6),  # week 9 isn't finished: ignored
    ]
    score = score_calls(calls, {(4, 1, 2): outcome})
    cats = score["categories"]
    assert score["pairings"] == 1 and cats["n"] == 3
    assert cats["brier"] == pytest.approx((0.1**2 + 0.2**2 + 0.1**2) / 3)
    assert cats["hit"] == 1.0  # the tie isn't a call either way
    assert score["matchups"]["brier"] == pytest.approx(0.09)
    # PTS ended +100 against +60 projected: 2 sd. TO ended -10 (ten more
    # turnovers) against -20: 1 sd. REB ended level against +5: -1 sd.
    assert score["spread"]["rms"] == pytest.approx((6 / 3) ** 0.5)
    pts = next(row for row in score["by_category"] if row["cat"] == "PTS")
    assert pts["totals_gap"] == pytest.approx(((800 / 1000 - 1) + (700 / 940 - 1)) / 2)
    assert score_calls(calls, {}) is None


def test_a_snapshot_forecasts_every_pairing_of_its_week(today):
    calls = forecast_league(today)
    period = today.league.matchup_period
    pairs = {(m.home.team_id, m.away.team_id) for m in today.matchups if m.period == period}
    assert {(c.home, c.away) for c in calls} == pairs and len(pairs) > 1
    assert all(0.0 <= c.p <= 1.0 and c.period == period for c in calls)
    per_pair = len(today.league.categories) + 1  # the categories and the matchup
    assert len(calls) == per_pair * len(pairs)


def _next_week(snap):
    """The same league a week on, with this week's matchups finished the
    way the home side was leading."""
    period = snap.league.matchup_period
    done = []
    for m in snap.matchups:
        if m.period != period or m.away is None:
            done.append(m)
            continue
        results = {}
        for cat in snap.league.categories:
            a, b = m.home.stats.get(cat, 0.0), m.away.stats.get(cat, 0.0)
            ahead = (a < b) if cat == "TO" else (a > b)
            results[cat] = "TIE" if a == b else "WIN" if ahead else "LOSS"
        wins = sum(1 for r in results.values() if r == "WIN")
        losses = sum(1 for r in results.values() if r == "LOSS")
        winner = "HOME" if wins > losses else "AWAY" if losses > wins else "TIE"
        done.append(replace(m, home=replace(m.home, results=results), winner=winner))
    return replace(
        snap,
        fetched_at="2026-10-22T16:00:00+00:00",
        league=replace(snap.league, matchup_period=period + 1),
        matchups=done,
    )


def test_backtest_scores_a_week_once_a_later_snapshot_shows_it_finished(today, tmp_path, capsys):
    assert run_backtest([today]) is None  # nothing finished yet
    later = _next_week(today)
    period = today.league.matchup_period
    assert sum(1 for week, *_ in finals([today, later]) if week == period) == 5
    result = run_backtest([today, later])
    score = result["models"]["rosters as they stand"]
    assert score["pairings"] == 5 and score["categories"]["n"] == 45
    assert 0.0 <= score["categories"]["brier"] <= 1.0
    text = render_backtest(result)
    assert "rosters as they stand" in text and "By category" in text

    store = SnapshotStore(tmp_path / "history.db")
    for snap in (today, later):
        store.save(snap, date.fromisoformat(snap.fetched_at[:10]))
    assert main(["backtest", "--db", str(tmp_path / "history.db")]) == 0
    assert "Backtest: 2 snapshots" in capsys.readouterr().out
    assert main(["backtest", "--db", str(tmp_path / "missing.db")]) == 1


def test_projection_errors_need_a_finished_week(today):
    assert projection_errors([]) is None
    assert projection_errors([today]) is None
