"""Streaming plan: which pickups, on which days and for whom, to spend the
acquisitions left in this matchup.

Greedy, one acquisition at a time: every candidate free agent is tried on
his first remaining game day (once a waived player clears) against every
droppable player, the dropped player keeping his games up to the day
before. The swap that adds the most expected categories won is kept, and
the search repeats on the new roster schedule until acquisitions run out
or no swap is worth one. A streamer the plan adds can himself be dropped
later, after his games. Only the weakest players are ever dropped, and the
center limit is respected.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import SideProjection, category_outlook, matchup_outlook, project_side
from fantasy.analysis.schedule import game_started
from fantasy.analysis.simulator import playable_from
from fantasy.espn.constants import BENCH_SLOT, C_SLOT, IR_SLOT
from fantasy.models import RosterSpot
from fantasy.timeutil import day_label

CANDIDATES = 25
DROPPABLE = 3
# A pickup has to add this many expected categories to be worth one of the
# limited acquisitions.
MIN_GAIN = 0.03

Window = tuple[date | None, date | None]


def _first_game_day(ctx: Context, player_id: int, earliest: date | None) -> date | None:
    team_id = ctx.snap.players[player_id].pro_team_id
    for sp in ctx.sps:
        day = ctx.calendar.date_of(sp)
        if day is None or (earliest and day < earliest):
            continue
        for game in ctx.calendar.by_sp.get(sp, []):
            if team_id in (game.home_id, game.away_id) and not game_started(game, ctx.now):
                return day
    return None


def _active(windows: dict[int, Window], pid: int, day: date) -> bool:
    start, end = windows.get(pid, (None, None))
    return (start is None or start <= day) and (end is None or end >= day)


def _outlook(ctx: Context, side: SideProjection, theirs: SideProjection) -> tuple[dict, dict]:
    projected = [
        o
        for c in ctx.snap.league.categories
        if (o := category_outlook(c, side, theirs)) is not None
    ]
    return matchup_outlook(projected), {o["cat"]: o["p_win"] for o in projected}


def plan_streams(
    ctx: Context,
    mine: SideProjection,
    theirs: SideProjection,
    free_agent_ids: list[int],
    acquisitions_left: int,
) -> dict:
    team = mine.team
    players = ctx.snap.players
    c_limit = ctx.snap.league.c_limit
    ir_ids = [s.player_id for s in team.roster if s.slot_id == IR_SLOT]
    members = [s.player_id for s in team.roster if s.slot_id != IR_SLOT]
    droppable = sorted(members, key=lambda pid: ctx.values.get(pid, 0.0))[:DROPPABLE]
    droppable_start = list(droppable)
    windows: dict[int, Window] = {}
    base, base_p = _outlook(ctx, mine, theirs)
    current, current_p = base, base_p
    current_side = mine
    pool = [pid for pid in free_agent_ids[:CANDIDATES] if pid in players]
    steps = []
    added: set[int] = set()

    def project(roster_ids: list[int], plan_windows: dict[int, Window]) -> SideProjection:
        roster = [RosterSpot(pid, BENCH_SLOT) for pid in roster_ids]
        roster += [RosterSpot(pid, IR_SLOT) for pid in ir_ids]
        return project_side(
            ctx, replace(team, roster=roster), mine.side, elapsed=mine.elapsed, windows=plan_windows
        )

    for _ in range(max(0, acquisitions_left)):
        best = None
        for fa_id in pool:
            day = _first_game_day(ctx, fa_id, playable_from(players[fa_id], ctx))
            if day is None:
                continue
            for drop_id in droppable:
                if not _active(windows, drop_id, day):
                    continue
                active_after = [
                    pid for pid in members if pid != drop_id and _active(windows, pid, day)
                ]
                centers = sum(
                    1
                    for pid in active_after + [fa_id] + ir_ids
                    if C_SLOT in players[pid].eligible_slots
                )
                if C_SLOT in players[fa_id].eligible_slots and centers > c_limit:
                    continue
                trial = dict(windows)
                trial[drop_id] = (windows.get(drop_id, (None, None))[0], day - timedelta(days=1))
                trial[fa_id] = (day, None)
                side = project(members + [fa_id], trial)
                outlook, p_by_cat = _outlook(ctx, side, theirs)
                gain = outlook["expected_wins"] - current["expected_wins"]
                if best is None or gain > best[0]:
                    best = (gain, fa_id, drop_id, day, trial, side, outlook, p_by_cat)
        if best is None or best[0] < MIN_GAIN:
            break
        gain, fa_id, drop_id, day, trial, side, outlook, p_by_cat = best
        steps.append(
            {
                "day": day_label(day),
                "date": day.isoformat(),
                "add": players[fa_id].name,
                "add_id": fa_id,
                "add_team": players[fa_id].pro_team,
                "waiver": players[fa_id].pool_status == "WAIVERS",
                "drop": players[drop_id].name,
                "drop_id": drop_id,
                "drop_is_streamer": drop_id in added,
                "gain": gain,
                "expected_after": outlook["expected_wins"],
                "p_win_after": outlook["p_win_matchup"],
                "usable_games_added": side.usable_remaining - current_side.usable_remaining,
            }
        )
        members.append(fa_id)
        added.add(fa_id)
        droppable.remove(drop_id)  # his spot is gone; he can't be dropped twice
        droppable.append(fa_id)
        windows = trial
        pool.remove(fa_id)
        current, current_p, current_side = outlook, p_by_cat, side

    return {
        "base": base,
        "final": current,
        # Found greediest first; carried out in date order.
        "steps": sorted(steps, key=lambda step: step["date"]),
        "acquisitions_left": acquisitions_left,
        "droppable": [players[pid].name for pid in droppable_start],
        "usable_before": mine.usable_remaining,
        "usable_after": current_side.usable_remaining,
        "categories": [
            {"cat": cat, "before": base_p[cat], "after": current_p.get(cat, base_p[cat])}
            for cat in base_p
        ],
    }
