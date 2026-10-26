from math import comb

import pytest

from fantasy.analysis.advanced import double_double, shooting
from fantasy.analysis.context import Context
from fantasy.analysis.matchup import (
    SideProjection,
    matchup_outlook,
    record_odds,
    targets,
)
from fantasy.analysis.schedule import plan_days
from fantasy.models import Game, Player, StatLine, Team
from fantasy.report import render_report
from tests.helpers import game, snapshot


def test_record_odds_is_a_poisson_binomial():
    odds = record_odds([0.5] * 9)
    assert sum(odds) == pytest.approx(1.0)
    assert odds == pytest.approx([comb(9, k) / 2**9 for k in range(10)])
    assert record_odds([1.0, 0.0, 1.0]) == pytest.approx([0, 0, 1, 0])


def test_matchup_outlook_counts_a_majority_of_categories():
    rows = [{"p_win": p} for p in (0.9, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1)]
    outlook = matchup_outlook(rows)
    assert outlook["expected_wins"] == pytest.approx(4.9)
    assert outlook["p_win_matchup"] == pytest.approx(outlook["p_at_least"][5])
    assert 0.5 < outlook["p_win_matchup"] < 0.9


def test_targets_cover_only_categories_short_of_a_likely_win():
    side = SideProjection(team=Team(id=1, name="x"), side=None, remaining_plans=[])
    rows = [
        {"cat": "3PM", "edge": -8.0, "sd": 6.0, "p_win": 0.2, "my_attempts": 0},
        {"cat": "FG%", "edge": -0.01, "sd": 0.02, "p_win": 0.33, "my_attempts": 500.0},
        {"cat": "PTS", "edge": 40.0, "sd": 30.0, "p_win": 0.9, "my_attempts": 0},
    ]
    found = {t["cat"]: t for t in targets(rows, side)}
    assert set(found) == {"3PM", "FG%"}
    assert found["3PM"]["to_even"] == 8.0
    assert found["3PM"]["to_likely"] == pytest.approx(8.0 + 0.5244 * 6.0)
    assert found["FG%"]["makes_to_likely"] == pytest.approx((0.01 + 0.5244 * 0.02) * 500)


def test_matchup_view_has_outlook_and_targets(view):
    mu = view["matchup"]
    expected = sum(r["p_win"] for r in mu["projected"])
    assert mu["outlook"]["expected_wins"] == pytest.approx(expected)
    assert all(t["p_win"] < 0.7 for t in mu["targets"])


def test_waiver_pickup_only_plays_once_he_clears():
    pickup = Player(id=9, name="Waiver C", pro_team_id=5, eligible_slots=[4, 11])
    games = [
        game(1, 10, "2026-10-15T23:30:00+00:00", 5, 6),
        game(2, 11, "2026-10-16T23:30:00+00:00", 5, 7),
    ]
    snap = snapshot([pickup], [(9, 12)], games, {4: 1, 11: 1, 12: 1}, sps=[10, 11])
    ctx = Context.build(snap)
    team = snap.team(1)
    free = plan_days(ctx.calendar, snap, team, {}, ctx.sps, ctx.now)
    assert [9 in p.started for p in free] == [True, True]
    held = plan_days(
        ctx.calendar,
        snap,
        team,
        {},
        ctx.sps,
        ctx.now,
        windows={9: (ctx.calendar.date_of(11), None)},
    )
    assert [9 in p.started for p in held] == [False, True]


def test_simulator_ranks_moves_by_their_effect_on_the_matchup(view):
    sim = view["moves"]
    assert sim["base"] == view["matchup"]["outlook"]
    assert 0 < len(sim["moves"]) <= 15
    changes = [m["expected_wins_change"] for m in sim["moves"]]
    assert changes == sorted(changes, reverse=True)
    my_roster = {r["id"] for r in view["my_team"]["roster"]}
    for move in sim["moves"]:
        assert move["drop"] in sim["drop_candidates"]
        assert move["add_id"] not in my_roster
        assert -1 <= move["p_win_change"] <= 1


def test_shooting_efficiency_formulas():
    line = StatLine(gp=1, min=30, pts=24, fgm=9, fga=18, ftm=4, fta=5, tpm=2, tpa=6)
    stats = shooting(line)
    assert stats["ts_pct"] == pytest.approx(24 / (2 * (18 + 0.44 * 5)), abs=0.001)
    assert stats["efg_pct"] == pytest.approx((9 + 1) / 18, abs=0.001)
    assert stats["tp_pct"] == pytest.approx(2 / 6, abs=0.001)
    assert double_double(Game(sp=1, line=StatLine(pts=12, reb=10)))
    assert not double_double(Game(sp=1, line=StatLine(pts=30, reb=9, ast=9)))


def test_advanced_stats_on_my_roster(view):
    rows = [r for r in view["my_team"]["roster"] if r["advanced"]]
    assert rows
    for row in rows:
        adv = row["advanced"]
        assert 0.3 < adv["ts_pct"] < 0.8
        if adv["consistency"]:
            cons = adv["consistency"]
            assert cons["floor"] <= cons["ceiling"] and cons["sd"] >= 0
        if adv["played_share"] is not None:
            assert 0 <= adv["played_share"] <= 1


def test_season_totals_rank_every_team(view):
    rows = view["season_standings"]
    assert len(rows) == 10
    for cat in rows[0]["values"]:
        best = min(rows, key=lambda r: r["ranks"][cat])
        values = [r["values"][cat] for r in rows]
        assert best["values"][cat] == (min(values) if cat == "TO" else max(values))


def test_report_shows_win_chances_simulator_and_advanced(view):
    text = render_report(view)
    assert "Win chances: expected categories won" in text
    assert "## ADD/DROP SIMULATOR" in text and "| Add | Team | Drop |" in text
    assert "- Advanced (season): TS%" in text
    assert "## STANDINGS AND SEASON STATS (as on ESPN)" in text
    assert "-0.00" not in text


def test_streaming_plan_uses_acquisitions_well(view, today):
    plan = view["stream_plan"]
    assert len(plan["steps"]) <= plan["acquisitions_left"]
    assert plan["final"]["expected_wins"] >= plan["base"]["expected_wins"]
    dropped = [s["drop_id"] for s in plan["steps"]]
    added = [s["add_id"] for s in plan["steps"]]
    assert len(dropped) == len(set(dropped))  # nobody is dropped twice
    assert len(added) == len(set(added))
    original = {s.player_id for s in today.team(1).roster}
    for step in plan["steps"]:
        assert step["gain"] >= 0.03
        assert step["add_id"] not in original
        assert step["drop_id"] in original or step["drop_is_streamer"]
    assert [s["date"] for s in plan["steps"]] == sorted(s["date"] for s in plan["steps"])


def test_streaming_plan_respects_no_acquisitions(today):
    from fantasy.analysis.context import Context
    from fantasy.analysis.matchup import project_side, sides_for
    from fantasy.analysis.planner import plan_streams

    ctx = Context.build(today)
    me = ctx.my_team
    my_side, opp_side = sides_for(ctx, me.id)
    mine = project_side(ctx, me, my_side)
    theirs = project_side(ctx, today.team(ctx.opponent_id(me.id)), opp_side)
    plan = plan_streams(ctx, mine, theirs, today.free_agent_ids, 0)
    assert plan["steps"] == [] and plan["final"] == plan["base"]


def test_category_strategy_classifies_by_odds_and_leverage(snapshots):
    from fantasy.analysis.view import build_view
    from tests.conftest import RIGA

    week, yesterday, today = snapshots
    st = build_view(today, yesterday, week, RIGA, punt=("TO",))["strategy"]
    plans = {r["cat"]: r for r in st["categories"]}
    assert plans["TO"]["plan"] == "Punted"
    assert plans["TO"]["leverage"] < 0  # every streamed game adds turnovers
    for row in st["categories"]:
        if row["plan"] == "Locked":
            assert row["p_win"] >= 0.9
        if row["plan"] == "Concede":
            assert row["p_win"] <= 0.1
        if row["plan"] == "Chase":
            assert 0.1 < row["p_win"] < 0.7 and row["leverage"] > 0
    chase_leverage = [plans[c]["leverage"] for c in st["chase"]]
    assert chase_leverage == sorted(chase_leverage, reverse=True)


def test_next_matchup_preview(view):
    nm = view["next_matchup"]
    assert nm["period"] == view["meta"]["matchup_period"] + 1
    assert nm["opponent"] == "Bullu Kojas"
    assert len(nm["days"]) == 7 and nm["dates"][0].startswith("Mon")
    assert nm["games"]["me"]["usable"] <= nm["games"]["me"]["scheduled"]
    assert 0 <= nm["outlook"]["p_win_matchup"] <= 1


def test_play_chance_discounts_doubtful_players_and_drops_out_ones():
    from datetime import date

    from fantasy.analysis.schedule import play_chance

    today = date(2026, 10, 15)
    tomorrow, later = date(2026, 10, 16), date(2026, 10, 18)
    healthy = Player(id=1, name="A")
    dtd = Player(id=2, name="B", injury_status="DAY_TO_DAY")
    out = Player(id=3, name="C", injury_status="OUT")
    back = Player(id=4, name="D", injury_status="OUT", expected_return="2026-10-17")
    assert play_chance(healthy, today, today) == 1.0
    assert play_chance(dtd, tomorrow, today) == pytest.approx(0.7)
    assert play_chance(dtd, later, today) == pytest.approx(0.85)
    assert play_chance(out, later, today) == 0.0
    assert play_chance(back, tomorrow, today) == 0.0
    assert play_chance(back, later, today) == pytest.approx(0.7)


def test_game_counts_cover_every_pairing_with_mine_first(view):
    rows = view["game_counts"]
    assert len(rows) == 10
    assert rows[0]["is_me"] and rows[1]["team"] == rows[0]["opponent"]
    for a, b in zip(rows[::2], rows[1::2], strict=True):
        assert a["edge"] == pytest.approx(-b["edge"])
    for r in rows:
        assert r["expected_remaining"] <= r["usable_remaining"] <= r["scheduled_remaining"]
        assert r["expected_total"] == pytest.approx(
            r["played"] + r["expected_remaining"] + r["stream_games"], abs=0.11
        )
        assert r["stream_games"] == 0 if r["is_me"] else r["stream_games"] >= 0
    mine = view["matchup"]["games"]["me"]
    # The demo has a DTD player on my team and an OUT one on IR.
    assert mine["uncertain_games"] > 0
    assert mine["expected_remaining"] < mine["usable_remaining"]


def test_what_if_covers_every_add_and_drop_pair(view):
    w = view["what_if"]
    assert w["adds"] and w["drops"]
    assert len(w["results"]) == len(w["adds"]) * len(w["drops"])
    n = len(w["categories"])
    assert len(w["base"]["p_win"]) == n
    row = w["results"][f"{w['adds'][0]['id']}:{w['drops'][0]['id']}"]
    assert len(row) == len(w["columns"]) + n
    assert 0 <= row[0] <= 1
    # The simulator's best move for a free agent agrees with the grid.
    move = view["moves"]["moves"][0]
    grid = w["results"][f"{move['add_id']}:{move['drop_id']}"]
    assert grid[0] == pytest.approx(move["p_win_after"], abs=0.001)


def test_week_grid_marks_each_game_for_my_players(view):
    grid = view["week_grid"]
    assert len(grid["days"]) == 7
    kinds = {c["kind"] for p in grid["players"] for c in p["cells"].values()}
    assert {"start", "played"} <= kinds
    assert "out" in kinds  # the demo's IR player
    for p in grid["players"]:
        assert p["games"] == len(p["cells"])
        assert all(c["vs"] for c in p["cells"].values())
    future = [d for d in grid["days"] if not d["past"]]
    assert future and all(d["open_slots"] is not None for d in future)


def test_opponent_streaming_raises_their_games_and_projection(view):
    from fantasy.analysis.streaming import ASSUMED_WEEKLY_ADDS

    s = view["matchup"]["opp_streaming"]
    assert 0 < s["expected_adds"] <= min(s["acquisitions_left"], ASSUMED_WEEKLY_ADDS) + 1e-9
    assert s["games"] > 0
    opp = view["matchup"]["games"]["opp"]
    assert opp["stream_games"] == pytest.approx(s["games"], abs=0.05)
    assert view["matchup"]["games"]["me"]["stream_games"] == 0


def test_weekly_rate_prefers_own_then_league_pace(snapshots):
    import copy

    from fantasy.analysis.streaming import weekly_rate

    today = copy.deepcopy(snapshots[2])  # the fixture is shared
    ctx = Context.build(today)
    period = today.league.matchup_period
    team, other = today.teams[0], today.teams[1]
    for t in today.teams:
        t.matchup_acquisitions = {period: 1}
    assert weekly_rate(ctx, team)[1] == "assumed"
    other.matchup_acquisitions = {period - 1: 4, period: 0}
    assert weekly_rate(ctx, team) == (4.0, "league pace")
    team.matchup_acquisitions = {period - 2: 1, period - 1: 3, period: 2}
    assert weekly_rate(ctx, team) == (2.0, "own pace")


def test_player_cards_cover_rosters_and_free_agents(view, today):
    cards = view["player_cards"]
    rostered = {s.player_id for t in today.teams for s in t.roster}
    assert rostered <= {int(k) for k in cards}
    mine = view["my_team"]["roster"][0]
    card = cards[str(mine["id"])]
    assert card["name"] == mine["name"] and card["owner"] == "MY TEAM"
    assert card["games"] and len(card["games"]) <= 10
    assert card["games"][0]["vs"] and "pts" in card["games"][0]
    assert "season" in card["splits"] or "projected" in card["splits"]
    assert card["values"]
    fa = cards[str(view["free_agents"][0]["id"])]
    assert fa["owner"] in ("FA", "WA")


def test_day_breakdown_and_exact_games_from_daily_lineups(snapshots):
    import copy

    from fantasy.analysis.matchup import day_breakdown, played_games, project_side, sides_for

    snap = copy.deepcopy(snapshots[2])
    ctx = Context.build(snap)
    me = snap.my_team_id
    opp = ctx.opponent_id(me)
    first = ctx.sps[0]
    base = {k: 0.0 for k in ("PTS", "REB", "AST", "STL", "BLK", "TO", "3PM", "FTM", "FTA")}
    snap.daily_totals = {
        first: {
            me: base | {"GP": 6, "PTS": 120, "TO": 10, "FGM": 40, "FGA": 80},
            opp: base | {"GP": 4, "PTS": 90, "TO": 12, "FGM": 30, "FGA": 70},
        }
    }
    ctx = Context.build(snap)
    (row,) = day_breakdown(ctx, me, opp)
    assert row["games"] == {"me": 6, "opp": 4}
    assert row["cats"]["PTS"]["leader"] == "me" and row["cats"]["TO"]["leader"] == "me"
    assert row["cats"]["FG%"]["me"] == 0.5
    my_side, _ = sides_for(ctx, me)
    assert played_games(ctx, project_side(ctx, snap.team(me), my_side)) == 6


def test_stars_may_rest_on_the_second_night_of_a_back_to_back():
    from datetime import date

    from fantasy.analysis.schedule import REST_CHANCE, play_chance

    today = date(2026, 10, 15)
    star = Player(id=1, name="Star")
    assert play_chance(star, today, today, rest=True) == pytest.approx(REST_CHANCE)
    dtd = Player(id=2, name="DTD star", injury_status="DAY_TO_DAY")
    assert play_chance(dtd, today, today, rest=True) == pytest.approx(0.7 * REST_CHANCE)


def test_back_to_back_rest_marks_only_top_players(today):
    import copy

    from fantasy.analysis.schedule import plan_days, star_cutoff

    snap = copy.deepcopy(today)
    ctx = Context.build(snap)
    cutoff = star_cutoff(ctx.values)
    team = snap.team(snap.my_team_id)
    for plan in plan_days(ctx.calendar, snap, team, ctx.values, ctx.sps, ctx.now):
        for pid in plan.rest:
            assert ctx.values[pid] >= cutoff
            assert ctx.calendar.back_to_back(snap.players[pid].pro_team_id, plan.date)
            assert plan.chance[pid] < 1.0


def test_pickup_ideas_only_on_open_days_and_for_players_who_play(view, today):
    from fantasy.analysis.context import Context as Ctx

    ctx = Ctx.build(today)
    grid = view["week_grid"]
    adds = {a["id"] for a in view["what_if"]["adds"]}
    for day in grid["days"]:
        if day["past"] or not day["open_slots"]:
            assert day["ideas"] == []
        for idea in day["ideas"]:
            assert idea["id"] in adds and idea["gain"] > 0
            player = today.players[idea["id"]]
            games = ctx.calendar.team_games(player.pro_team_id, ctx.sps)
            assert any(g.sp == day["sp"] for g in games)
    assert any(day["ideas"] for day in grid["days"])


def test_season_outlook_simulates_the_rest_of_the_regular_season(view, today):
    so = view["season_outlook"]
    assert so["regular_periods"] == 18 and so["playoff_teams"] == 4
    assert so["playoff_weeks"] == [19, 20]
    rows = so["rows"]
    assert len(rows) == len(today.teams)
    assert sum(r["playoff_pct"] for r in rows) == pytest.approx(4.0, abs=0.01)
    assert [r["playoff_pct"] for r in rows] == sorted(
        (r["playoff_pct"] for r in rows), reverse=True
    )
    for r in rows:
        assert 1 <= r["avg_seed"] <= len(rows)


def test_category_odds_favour_the_stronger_side():
    from fantasy.analysis.season import _cat_odds

    strong = {"pts": 20.0, "fgm": 8.0, "fga": 16.0, "to": 1.0}
    weak = {"pts": 15.0, "fgm": 7.0, "fga": 16.0, "to": 2.0}
    assert _cat_odds(strong, weak, 33, "PTS") > 0.9
    assert _cat_odds(strong, weak, 33, "FG%") > 0.5
    assert _cat_odds(strong, weak, 33, "TO") > 0.9  # fewer turnovers wins
    assert _cat_odds(weak, strong, 33, "PTS") == pytest.approx(
        1 - _cat_odds(strong, weak, 33, "PTS")
    )


def test_card_history_counts_games_missed_while_out(today):
    import copy

    from fantasy.analysis.cards import status_history
    from fantasy.timeutil import parse_iso
    from tests.conftest import RIGA

    snap = copy.deepcopy(today)
    ctx = Context.build(snap)
    player = next(p for p in snap.players.values() if p.games and p.pro_team_id)
    first_game = min(
        (g for g in ctx.calendar.by_team[player.pro_team_id] if parse_iso(g.start) < ctx.now),
        key=lambda g: g.start,
    )
    player.games = []  # no box scores since: every team game was missed
    since = parse_iso(first_game.start).isoformat()
    rows = status_history(ctx, player, [("OUT", since)], RIGA)
    team_games = sum(
        1
        for g in ctx.calendar.by_team[player.pro_team_id]
        if parse_iso(first_game.start) <= parse_iso(g.start) < ctx.now
    )
    assert rows == [{"status": "OUT", "since": rows[0]["since"], "missed": team_games}]


def test_lineup_habits_count_games_left_on_the_bench(today):
    import copy

    from fantasy.analysis.habits import lineup_habits
    from fantasy.timeutil import EASTERN

    snap = copy.deepcopy(today)
    ctx = Context.build(snap)
    day_sp = next(
        sp
        for sp in sorted(ctx.calendar.by_sp)
        if ctx.calendar.date_of(sp) < ctx.now.astimezone(EASTERN).date()
        and any(any(g.sp == sp and g.played for g in p.games) for p in snap.players.values())
    )
    games = ctx.calendar.by_sp[day_sp]
    playing = {g.home_id for g in games} | {g.away_id for g in games}
    benched = next(
        p for p in snap.players.values() if any(g.sp == day_sp and g.played for g in p.games)
    )
    idle = next(p for p in snap.players.values() if p.pro_team_id and p.pro_team_id not in playing)
    slots = {0: 1}
    snap.league.lineup_slots = slots | {12: 3}
    snap.lineups = {day_sp: {2: {idle.id: 0, benched.id: 12}}}
    ctx = Context.build(snap)
    habits = lineup_habits(ctx, 2)
    assert habits["days"] == 1 and habits["lost_games"] == 1
    assert habits["waste_rate"] == 0.0  # too few days to judge a habit


def test_hot_free_agents_are_free_healthy_and_explained(view, today):
    rows = view["hot_free_agents"]
    assert rows and len(rows) <= 10
    free = set(today.free_agent_ids)
    for r in rows:
        assert r["id"] in free and r["signals"]
        assert today.players[r["id"]].injury_status not in ("OUT", "INJURY_RESERVE")
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)


def test_rest_of_season_games_scale_value(view, today):
    from fantasy.analysis.season import rest_of_season_games

    ctx = Context.build(today)
    games, median = rest_of_season_games(ctx)
    assert median > 0
    row = view["rankings"]["rows"][view["rankings"]["default"]][0]
    team = today.players[row["id"]].pro_team_id
    assert row["ros_games"] == games[team]
    assert row["ros_factor"] == pytest.approx(games[team] / median, abs=0.001)
    card = view["player_cards"][str(row["id"])]
    assert card["ros_games"] == games[team]


def test_punt_analysis_compares_options(view):
    pa = view["punt_analysis"]
    labels = [r["label"] for r in pa["rows"]]
    assert labels[0] == "No punt" and "TO" in labels
    assert any(" + " in label for label in labels)
    none = pa["rows"][0]
    assert none["cost"] == 0 and none["place_change"] == 0
    for r in pa["rows"][1:]:
        assert r["cost"] > 0 and r["expected_cats"] < none["expected_cats"] + 1e-9
        assert 1 <= r["place"] <= 10
    assert pa["best"] in labels


def test_recap_of_the_previous_matchup(view, today):
    r = view["recap"]
    assert r["period"] == today.league.matchup_period - 1
    assert len(r["categories"]) == len(today.league.categories)
    assert r["score"]["wins"] + r["score"]["losses"] + r["score"]["ties"] == len(r["categories"])
    for c in r["categories"]:
        assert (c["margin"] > 0) == (c["result"] == "WIN") or c["result"] == "TIE"


def test_first_forecast_scores_the_calls():
    from fantasy.analysis.accuracy import first_forecast

    recap = {
        "period": 4,
        "categories": [{"cat": "PTS", "result": "WIN"}, {"cat": "REB", "result": "LOSS"}],
    }
    forecasts = [
        ("2026-10-05T08:00:00+00:00", 4, "PTS", 0.7),
        ("2026-10-05T08:00:00+00:00", 4, "REB", 0.6),
        ("2026-10-05T08:00:00+00:00", 4, "*", 0.55),
        ("2026-10-06T08:00:00+00:00", 4, "*", 0.9),
    ]
    f = first_forecast(forecasts, recap)
    assert f["p_win_matchup"] == 0.55 and f["called"] == 1 and f["judged"] == 2


def test_trade_ideas_improve_me_without_hurting_the_partner(view, today):
    ideas = view["trade_ideas"]
    assert ideas
    mine = {s.player_id for s in today.team(today.my_team_id).roster}
    for t in ideas:
        assert t["avg_rank_after"] < t["avg_rank_before"]
        assert t["partner_rank_after"] <= t["partner_rank_before"] + 0.1
        assert {p["id"] for p in t["give"]} <= mine
        assert len(t["get"]) == 1 and 1 <= len(t["give"]) <= 2
    partners = [t["partner_id"] for t in ideas]
    assert all(partners.count(p) <= 2 for p in partners)
