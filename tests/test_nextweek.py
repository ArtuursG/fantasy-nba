from fantasy.analysis.actions import build_actions
from fantasy.analysis.matchup import project_side, sides_for
from fantasy.analysis.nextweek import next_week_setup, setup_text
from fantasy.notify import alert_text


def _sides(ctx):
    me = ctx.my_team
    mine, theirs = sides_for(ctx, me.id)
    opp = ctx.snap.team(ctx.opponent_id(me.id))
    return project_side(ctx, me, mine), project_side(ctx, opp, theirs)


def test_setup_swaps_my_weakest_players_for_next_weeks_matchup(ctx, today):
    mine, theirs = _sides(ctx)
    setup = next_week_setup(ctx, mine, theirs, 3)
    assert setup["period"] == today.league.matchup_period + 1
    assert setup["steps"] and len(setup["steps"]) <= 3
    assert setup["final"]["expected_wins"] > setup["base"]["expected_wins"]
    roster = {s.player_id for s in today.team(today.my_team_id).roster}
    weakest = set(sorted(roster, key=lambda pid: ctx.values.get(pid, 0.0))[:3])
    for step in setup["steps"]:
        assert step["add_id"] in today.free_agent_ids and step["drop_id"] in weakest
        assert step["gain"] >= 0.03 and step["add_games"] > 0
        # Kept for what it adds over both weeks together.
        assert step["gain"] + step["this_week"]["categories_change"] >= 0.05
        assert step["add"] in setup_text(step) and step["drop"] in setup_text(step)
    assert len({s["add_id"] for s in setup["steps"]}) == len(setup["steps"])
    assert len({s["drop_id"] for s in setup["steps"]}) == len(setup["steps"])
    assert next_week_setup(ctx, mine, theirs, 0)["steps"] == []


def test_setup_comes_after_this_weeks_streaming_plan(view, ctx):
    plan, setup = view["stream_plan"], view["next_setup"]
    assert setup["planned_first"] == len(plan["steps"])
    assert setup["acquisitions_left"] == plan["acquisitions_left"] - len(plan["steps"])
    taken = {s["add_id"] for s in plan["steps"]} | {s["drop_id"] for s in plan["steps"]}
    for step in setup["steps"]:
        assert step["add_id"] not in taken and step["drop_id"] not in taken


def test_setup_goes_on_the_to_do_list_in_a_weeks_last_days(view):
    mine_setup = view["next_setup"]
    step = {
        "add": "Late Pickup",
        "add_id": 1,
        "add_team": "BOS",
        "add_games": 4,
        "waiver": False,
        "drop": "Bench Guy",
        "drop_id": 2,
        "drop_games": 2,
        "gain": 0.4,
        "this_week": {"categories_change": -0.02},
    }
    due = {**view, "next_setup": {**mine_setup, "due": True, "steps": [step]}}
    due["actions"] = build_actions(due)
    items = [i for i in due["actions"]["items"] if i["kind"] == "setup"]
    assert [i["text"] for i in items] == [
        "Add Late Pickup (BOS, 4 games), drop Bench Guy (2 games)"
    ]
    assert "+0.4 expected categories next week" in items[0]["why"]
    assert "Next week: Add Late Pickup" in alert_text(due)

    early = {**view, "next_setup": {**mine_setup, "due": False, "steps": [step]}}
    assert not [i for i in build_actions(early)["items"] if i["kind"] == "setup"]
