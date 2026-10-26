import pytest

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import call, team_strength, win_probability
from fantasy.analysis.roles import role_info
from fantasy.analysis.stats import Valuation, projection_line
from fantasy.models import Game, Player, StatLine
from tests.helpers import game, snapshot


def test_win_probability_and_calls():
    assert win_probability(5, 0) == 1.0
    assert win_probability(-5, 0) == 0.0
    assert win_probability(0, 0) == 0.5
    assert win_probability(10, 10) == pytest.approx(0.841, abs=0.001)
    assert call(0.7) == "Likely win" and call(0.3) == "Likely loss" and call(0.5) == "Swing"


def test_projection_line_blends_season_with_projection_and_recent():
    player = Player(
        id=1,
        name="x",
        stats={
            "season": StatLine(gp=10, min=30, pts=20),
            "projected": StatLine(gp=70, min=34, pts=24),
            "last15": StatLine(gp=5, min=36, pts=28),
        },
    )
    line = projection_line(player)
    base_pts = 0.5 * 20 + 0.5 * 24  # 10 games played vs a prior worth 10
    assert line.pts == pytest.approx(0.35 * 28 + 0.65 * base_pts)

    rookie = Player(id=2, name="y", stats={"projected": StatLine(gp=70, min=20, pts=9)})
    assert projection_line(rookie).pts == 9


def test_valuation_rewards_volume_efficiency_and_few_turnovers():
    pool = [
        StatLine(gp=10, min=30, fgm=7, fga=15, ftm=3, fta=4, pts=20, reb=5, to=2),
        StatLine(gp=10, min=30, fgm=5, fga=12, ftm=2, fta=3, pts=14, reb=4, to=2),
        StatLine(gp=10, min=30, fgm=9, fga=15, ftm=1, fta=3, pts=19, reb=10, to=3),
    ]
    valuation = Valuation.from_pool(pool, ["FG%", "PTS", "REB", "TO"])
    scores = valuation.by_cat(pool[2])
    assert scores["FG%"] > 0 and scores["REB"] > 0 and scores["TO"] < 0
    assert valuation.score(StatLine()) == -4.0


def _player_with_games(minutes_and_starts, sps):
    games = [
        Game(sp=sp, line=StatLine(gp=1, gs=1.0 if started else 0.0, min=m, pts=m / 2))
        for sp, (m, started) in zip(sps, minutes_and_starts, strict=True)
    ]
    return Player(id=1, name="Riser", pro_team_id=1, eligible_slots=[1, 5, 11], games=games)


def test_minutes_jump_and_new_starting_role():
    history = [(20, False)] * 10 + [(30, True)] * 5
    sps = list(range(1, 16))
    player = _player_with_games(history, sps)
    games = [game(i, sp, f"2026-10-{sp:02d}T00:00:00+00:00", 1, 2) for i, sp in enumerate(sps)]
    snap = snapshot([player], [(1, 12)], games, {1: 1, 11: 1, 12: 1}, sps=[16, 17])
    info = role_info(player, Context.build(snap), log_start=1)

    assert info.trend == "UP" and info.min_delta == pytest.approx(10)
    assert info.baseline_label == "previous 10 games"
    assert info.new_starter and not info.lost_start
    assert info.role == "Starter, ~30 MIN"


def test_return_from_injury_found_from_missed_team_games():
    sps = list(range(1, 13))
    played = [1, 2, 3, 4, 5, 6, 11, 12]  # missed 7-10
    player = _player_with_games([(32, True)] * 6 + [(20, True), (24, True)], played)
    games = [game(i, sp, f"2026-10-{sp:02d}T00:00:00+00:00", 1, 2) for i, sp in enumerate(sps)]
    snap = snapshot([player], [(1, 12)], games, {1: 1, 12: 1}, sps=[13, 14])
    info = role_info(player, Context.build(snap), log_start=1)
    assert info.returned == (4, 2)
    assert info.missed_now == 0


def test_demo_storylines_show_up_as_alerts(view, world):
    alerts = {a["player_id"]: a for a in view["alerts"]}

    dtd = world.rosters[1][4]
    assert "injury_change" in alerts[dtd]["kinds"] and alerts[dtd]["owner"] == "MY TEAM"
    returner = world.rosters[1][1]
    assert "returned" in alerts[returner]["kinds"]
    assert any("ramping up" in line for line in alerts[returner]["lines"])
    backup = world.free_agents[0]
    assert {"minutes_up", "new_starter", "teammate_out"} <= set(alerts[backup]["kinds"])
    rookie = world.free_agents[1]
    assert "rookie_rising" in alerts[rookie]["kinds"]
    surge = world.free_agents[2]
    assert "add_trend" in alerts[surge]["kinds"]
    star = max((world.players[p] for p in world.rosters[2][:8]), key=lambda p: p.quality)
    assert alerts[star.id]["owner"].startswith("OPPONENT") and alerts[star.id]["trend"] == "INJURY"
    # my team first, then free agents, then the opponent
    owners = [a["owner"] for a in view["alerts"]]
    assert (
        owners.index("MY TEAM")
        < owners.index("FA")
        < next(i for i, o in enumerate(owners) if o.startswith("OPPONENT"))
    )


def test_matchup_projection_is_consistent(view):
    mu = view["matchup"]
    assert mu["opp"]["name"] == "Sabiles Stealers"
    cats = [p["cat"] for p in mu["projected"]]
    assert cats == view["meta"]["categories"]
    current = {c["cat"]: c for c in mu["current"]}
    for row in mu["projected"]:
        assert 0.0 <= row["p_win"] <= 1.0
        if not row["cat"].endswith("%"):
            assert row["me"] >= current[row["cat"]]["me"]
            assert row["opp"] >= current[row["cat"]]["opp"]
    assert sorted(mu["likely_wins"] + mu["likely_losses"] + mu["swing"]) == sorted(cats)
    score = mu["score_now"]
    assert score["wins"] + score["losses"] + score["ties"] == 9


def test_strength_ranks_each_category_one_to_ten(ctx):
    strength = team_strength(ctx)
    assert len(strength) == 10
    for cat in ctx.snap.league.categories:
        ranks = sorted(s["ranks"][cat] for s in strength.values())
        assert ranks[0] == 1 and ranks[-1] <= 10
        best = min(strength.values(), key=lambda s: s["ranks"][cat])
        values = [s["values"][cat] for s in strength.values()]
        expected = min(values) if cat == "TO" else max(values)
        assert best["values"][cat] == expected


def test_free_agent_ranking_puts_the_opportunity_near_the_top(view, world):
    ids = [r["id"] for r in view["free_agents"]]
    assert len(ids) == 50
    assert ids.index(world.free_agents[0]) < 5
    backup = view["free_agents"][ids.index(world.free_agents[0])]
    assert any(r.startswith("Fill-in for") for r in backup["reasons"])
    assert backup["fill_in"] and backup["fill_in"][0]["player"]
    assert backup["projected_min"] > backup["espn_projected_min"] + 8
    for row in view["streamers"]:
        assert row["usable_remaining"] > 0


def test_changes_since_yesterday(view, world):
    changes = view["changes"]
    opp_moves = [m for m in changes["roster_moves"] if m["is_opp"]]
    assert len(opp_moves) == 1 and opp_moves[0]["added"] and opp_moves[0]["dropped"]
    statuses = {(c["player_id"], c["to"]) for c in changes["injuries"]}
    assert (world.rosters[1][4], "DTD") in statuses
    assert changes["bullets"][0].endswith("injury: Healthy -> DTD")
    assert "(your team)" in changes["bullets"][0]
    assert view["changes_week"]["since"] is not None


def test_new_transactions_are_marked_since_the_last_snapshot(view):
    rows = view["transactions"]
    assert [r["new"] for r in rows].count(True) == 1
    assert any(r["result"] and r["result"].startswith("claim failed") for r in rows)
    assert all(r["ts"] >= rows[-1]["ts"] for r in rows)


def test_acquisitions_waivers_and_ir(view):
    acq = view["acquisitions"]
    assert acq["limit"] == 5 and acq["used"] + acq["remaining"] == 5
    ranks = [w["rank"] for w in view["waiver_order"]]
    assert ranks == sorted(ranks) and len(ranks) == 10
    assert view["my_ir"]["players"][0]["health"].startswith("OUT")
    assert view["my_c_count"] == 3
