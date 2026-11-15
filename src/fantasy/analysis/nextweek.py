"""Setting up next week before this one ends.

Acquisitions are counted per matchup and the unused ones are gone on
Monday. A pickup made on the last day or two of a week costs one of this
week's, but most of what he plays is next week: the cheapest way there is
to make next week's roster better.

So every well-placed free agent is tried in place of each of my weakest
players for the whole of next matchup, against next week's opponent, and
the same swap is tried in the matchup still being played, from the day the
pickup could first play. A swap is kept for what it adds over both weeks
together, in expected categories, so a pickup that helps next week isn't
made at the cost of a category still in reach now. One at a time, as many
as this week still has acquisitions for.
"""

from __future__ import annotations

from dataclasses import replace

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import SideProjection, category_outlook, matchup_outlook, project_side
from fantasy.analysis.simulator import playable_from
from fantasy.espn.constants import BENCH_SLOT, C_SLOT, IR_SLOT, UNAVAILABLE_STATUSES
from fantasy.models import COUNTING_FIELDS, RosterSpot, Team
from fantasy.timeutil import EASTERN, day_label

CANDIDATES = 60
DROPPABLE = 3
# A swap has to add this many expected categories over the two weeks, and
# some of it next week (a pickup that only helps now is the streaming plan's).
MIN_GAIN = 0.05
MIN_NEXT_GAIN = 0.03
# It goes on the to-do list once this week has no more than this many days.
LAST_DAYS = 2


def _outlook(ctx: Context, mine: SideProjection, theirs: SideProjection) -> tuple[dict, dict]:
    rows = [
        row
        for cat in ctx.snap.league.categories
        if (row := category_outlook(cat, mine, theirs)) is not None
    ]
    return matchup_outlook(rows), {row["cat"]: row["p_win"] for row in rows}


def _with(team: Team, adds: list[int], drops: list[int]) -> Team:
    roster = [s for s in team.roster if s.player_id not in drops]
    return replace(team, roster=roster + [RosterSpot(pid, BENCH_SLOT) for pid in adds])


def next_week_setup(
    ctx: Context,
    mine_now: SideProjection | None,
    theirs_now: SideProjection | None,
    acquisitions_left: int,
    plan: dict | None = None,
) -> dict | None:
    """Pickups worth making before this matchup ends, for the next one.
    `plan` is this week's streaming plan: its pickups come first, so the
    setup starts from the roster they leave and uses the acquisitions they
    don't. None when there is no next matchup on the schedule."""
    snap, league = ctx.snap, ctx.snap.league
    me = ctx.my_team
    period = league.matchup_period + 1
    sps = sorted(league.matchup_periods.get(period) or [])
    opp = snap.team(ctx.opponent_id(me.id, period)) if me else None
    if me is None or opp is None or not sps:
        return None
    zero = dict.fromkeys(COUNTING_FIELDS, 0.0)
    wanted = set(sps)

    def project(team: Team) -> SideProjection:
        return project_side(ctx, team, None, elapsed=zero, sps=sps)

    def games(pid: int) -> int:
        return len(ctx.calendar.team_games(snap.players[pid].pro_team_id, sps))

    planned = (plan or {}).get("steps") or []
    plan_adds = {step["add_id"] for step in planned}
    plan_drops = {step["drop_id"] for step in planned}
    # A streamer the plan adds and drops again is on neither list.
    adds = sorted(plan_adds - plan_drops)
    drops = sorted(plan_drops - plan_adds)
    acquisitions_left = max(0, acquisitions_left - len(planned))

    theirs = project(opp)
    base_side = project(_with(me, adds, drops))
    base, base_odds = _outlook(ctx, base_side, theirs)

    pool = [
        pid
        for pid in snap.free_agent_ids
        if pid in ctx.lines
        and snap.players[pid].injury_status not in UNAVAILABLE_STATUSES
        and any(g.sp in wanted for g in ctx.calendar.by_team.get(snap.players[pid].pro_team_id, []))
    ]
    pool = sorted(pool, key=lambda pid: ctx.values.get(pid, 0.0), reverse=True)[:CANDIDATES]
    members = [s.player_id for s in me.roster if s.slot_id != IR_SLOT]
    ir_ids = [s.player_id for s in me.roster if s.slot_id == IR_SLOT]
    droppable = sorted(
        (pid for pid in members if pid not in drops), key=lambda pid: ctx.values.get(pid, 0.0)
    )[:DROPPABLE]
    c_limit = league.c_limit

    def centers(ids: list[int]) -> int:
        return sum(1 for pid in ids if C_SLOT in snap.players[pid].eligible_slots)

    def this_week(trial_adds: list[int], trial_drops: list[int]) -> dict | None:
        """The matchup still being played with these swaps, each pickup from
        the day he could first play."""
        if mine_now is None or theirs_now is None:
            return None
        start = {pid: playable_from(snap.players[pid], ctx) for pid in trial_adds}
        windows = {pid: (day, None) for pid, day in start.items() if day is not None}
        side = project_side(
            ctx,
            _with(mine_now.team, trial_adds, trial_drops),
            mine_now.side,
            elapsed=mine_now.elapsed,
            windows=windows or None,
        )
        return _outlook(ctx, side, theirs_now)[0]

    current, current_side = base, base_side
    now = this_week(adds, drops)
    steps = []
    for _ in range(max(0, acquisitions_left)):
        best = None
        for fa_id in pool:
            if fa_id in adds or fa_id in plan_adds:
                continue
            for drop_id in droppable:
                if drop_id in drops:
                    continue
                kept = [pid for pid in members if pid not in drops and pid != drop_id]
                if (
                    C_SLOT in snap.players[fa_id].eligible_slots
                    and centers(kept + adds + [fa_id] + ir_ids) > c_limit
                ):
                    continue
                side = project(_with(me, adds + [fa_id], drops + [drop_id]))
                outlook, odds = _outlook(ctx, side, theirs)
                gain = outlook["expected_wins"] - current["expected_wins"]
                if gain < MIN_NEXT_GAIN:
                    continue
                after_now = this_week(adds + [fa_id], drops + [drop_id])
                cost = after_now["expected_wins"] - now["expected_wins"] if after_now and now else 0
                if best is None or gain + cost > best[0]:
                    best = (gain + cost, fa_id, drop_id, side, outlook, odds, gain, after_now)
        if best is None or best[0] < MIN_GAIN:
            break
        _, fa_id, drop_id, side, outlook, odds, gain, after_now = best
        player, dropped = snap.players[fa_id], snap.players[drop_id]
        steps.append(
            {
                "add": player.name,
                "add_id": fa_id,
                "add_team": player.pro_team,
                "add_games": games(fa_id),
                "waiver": player.pool_status == "WAIVERS",
                "drop": dropped.name,
                "drop_id": drop_id,
                "drop_games": games(drop_id),
                "gain": gain,
                "p_win_after": outlook["p_win_matchup"],
                "usable_games_added": side.usable_remaining - current_side.usable_remaining,
                "helps": [
                    cat
                    for cat, p in sorted(odds.items(), key=lambda kv: base_odds[kv[0]] - kv[1])
                    if p - base_odds[cat] >= 0.03
                ][:4],
                "this_week": {
                    "p_win_before": now["p_win_matchup"],
                    "p_win_after": after_now["p_win_matchup"],
                    "categories_change": after_now["expected_wins"] - now["expected_wins"],
                }
                if after_now and now
                else None,
            }
        )
        adds.append(fa_id)
        drops.append(drop_id)
        current, current_side, now = outlook, side, after_now or now

    today = ctx.now.astimezone(EASTERN).date()
    days_left = sum(
        1 for sp in ctx.sps if (day := ctx.calendar.date_of(sp)) is not None and day >= today
    )
    first, last = ctx.calendar.date_of(sps[0]), ctx.calendar.date_of(sps[-1])
    return {
        "period": period,
        "opponent": opp.name,
        "dates": [day_label(first) if first else "", day_label(last) if last else ""],
        "acquisitions_left": acquisitions_left,
        "planned_first": len(planned),
        "days_left": days_left,
        "due": days_left <= LAST_DAYS and bool(steps),
        "base": {"expected_wins": base["expected_wins"], "p_win_matchup": base["p_win_matchup"]},
        "final": {
            "expected_wins": current["expected_wins"],
            "p_win_matchup": current["p_win_matchup"],
        },
        "usable_before": base_side.usable_remaining,
        "usable_after": current_side.usable_remaining,
        "droppable": [snap.player_name(pid) for pid in droppable],
        "steps": steps,
    }


def setup_text(step: dict) -> str:
    """'Add X (DAL, 4 games), drop Y (2 games): next week +0.4 categories'."""
    verb = "Claim" if step["waiver"] else "Add"
    return (
        f"{verb} {step['add']} ({step['add_team']}, {step['add_games']} games), drop "
        f"{step['drop']} ({step['drop_games']} games)"
    )
