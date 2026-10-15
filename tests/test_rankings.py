import copy
from statistics import fmean

import pytest

from fantasy.analysis.context import Context
from fantasy.analysis.rankings import default_range, rank_players
from fantasy.analysis.view import build_view
from fantasy.report import render_report
from tests.conftest import RIGA


def test_values_average_the_category_z_scores(ctx):
    rows, cats = rank_players(ctx, "season")
    assert cats == ctx.snap.league.categories
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0]["round"] == 1 and rows[10]["round"] == 2  # 10-team league
    for row in rows[:20]:
        assert row["value"] == pytest.approx(fmean(row["values"].values()), abs=0.011)
        assert row["value"] == row["league_value"]  # nothing punted
    values = [r["value"] for r in rows]
    assert values == sorted(values, reverse=True)


def test_punting_leaves_the_category_out_of_value_but_not_league_value(today):
    ctx = Context.build(today, punt=("TO",))
    rows, _ = rank_players(ctx, "season")
    for row in rows[:20]:
        others = [v for c, v in row["values"].items() if c != "TO"]
        assert row["value"] == pytest.approx(fmean(others), abs=0.011)
        assert row["league_value"] == pytest.approx(fmean(row["values"].values()), abs=0.011)
    pid = rows[0]["id"]
    line = ctx.lines[pid]
    assert ctx.values[pid] == pytest.approx(ctx.valuation.score(line, ("TO",)))


def test_rankings_cover_every_range_and_mark_owners(view, today):
    rankings = view["rankings"]
    assert [r["key"] for r in rankings["ranges"]] == [
        "season",
        "last30",
        "last15",
        "last7",
        "projection",
    ]
    assert rankings["default"] == "season"  # demo players have played 10+ games
    owners = {r["owner_short"] for r in rankings["rows"]["season"]}
    assert {"ME", "OPP", "FA"} <= owners
    mine = {s.player_id for s in today.team(1).roster}
    assert all(r["owner_short"] == "ME" for r in rankings["rows"]["season"] if r["id"] in mine)
    row = view["my_team"]["roster"][0]
    assert row["rank"] is not None and set(row["cat_values"]) == set(rankings["categories"])


def test_projection_is_the_default_range_before_games_are_played(today):
    assert default_range(Context.build(today)) == "season"
    early = copy.deepcopy(today)
    for player in early.players.values():
        if "season" in player.stats:
            player.stats["season"].gp = 2
    assert default_range(Context.build(early)) == "projection"


def test_report_states_the_punt_and_ranks_by_it(snapshots):
    week, yesterday, today = snapshots
    text = render_report(build_view(today, yesterday, week, RIGA, punt=("TO",)))
    assert "Strategy: punting TO." in text
    assert "| Rnd | Rank | Value | LeagV | Punt+ | Name |" in text
    plain = render_report(build_view(today, yesterday, week, RIGA))
    assert "Strategy:" not in plain and "| Rnd | Rank | Value | Name |" in plain
