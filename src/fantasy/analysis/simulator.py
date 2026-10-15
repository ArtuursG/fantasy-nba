"""Add/drop simulator: what a pickup would do to this matchup.

For each of the most interesting free agents, the roster is re-projected
with him in place of one of the weakest players (the drop that helps most
is kept), from the day he could actually play: right away for a free agent,
once he clears for a player on waivers. What was played so far stays as it
was. The result is the change in usable games, expected categories won,
the chance of winning the matchup, and each category's odds, plus the
rest-of-season value of the swap.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import (
    SideProjection,
    category_outlook,
    matchup_outlook,
    project_side,
)
from fantasy.espn.constants import BENCH_SLOT, IR_SLOT
from fantasy.models import Player, RosterSpot
from fantasy.timeutil import EASTERN, parse_iso

CANDIDATES = 15
DROP_CANDIDATES = 2


def playable_from(player: Player, ctx: Context) -> date | None:
    """First day a pickup could play: today for a free agent, the day his
    waiver period ends for a waived player (the next day when unknown)."""
    if player.pool_status != "WAIVERS":
        return None
    if player.waiver_clear:
        return parse_iso(player.waiver_clear).astimezone(EASTERN).date()
    return ctx.now.astimezone(EASTERN).date() + timedelta(days=1)


def _projected(ctx: Context, mine: SideProjection, theirs: SideProjection) -> list[dict]:
    return [
        outlook
        for cat in ctx.snap.league.categories
        if (outlook := category_outlook(cat, mine, theirs)) is not None
    ]


def simulate_moves(
    ctx: Context,
    mine: SideProjection,
    theirs: SideProjection,
    free_agent_ids: list[int],
    acquisitions_left: int | None,
) -> dict:
    base = _projected(ctx, mine, theirs)
    base_outlook = matchup_outlook(base)
    base_p = {r["cat"]: r["p_win"] for r in base}
    team = mine.team
    droppable = sorted(
        (s.player_id for s in team.roster if s.slot_id != IR_SLOT),
        key=lambda pid: ctx.values.get(pid, 0.0),
    )[:DROP_CANDIDATES]

    moves = []
    for fa_id in free_agent_ids[:CANDIDATES]:
        fa = ctx.snap.players[fa_id]
        start = playable_from(fa, ctx)
        best = None
        for drop_id in droppable:
            roster = [s for s in team.roster if s.player_id != drop_id]
            roster.append(RosterSpot(player_id=fa_id, slot_id=BENCH_SLOT))
            side = project_side(
                ctx,
                replace(team, roster=roster),
                mine.side,
                elapsed=mine.elapsed,
                available_from={fa_id: start} if start else None,
            )
            projected = _projected(ctx, side, theirs)
            outlook = matchup_outlook(projected)
            changes = sorted(
                ((r["cat"], r["p_win"] - base_p[r["cat"]]) for r in projected),
                key=lambda c: -abs(c[1]),
            )
            move = {
                "add_id": fa_id,
                "add": fa.name,
                "add_team": fa.pro_team,
                "drop_id": drop_id,
                "drop": ctx.snap.player_name(drop_id),
                "waiver_until": start.isoformat() if start else None,
                "usable_change": side.usable_remaining - mine.usable_remaining,
                "expected_wins_change": outlook["expected_wins"] - base_outlook["expected_wins"],
                "p_win_change": outlook["p_win_matchup"] - base_outlook["p_win_matchup"],
                "p_win_after": outlook["p_win_matchup"],
                "category_changes": [
                    {"cat": cat, "change": change} for cat, change in changes if abs(change) >= 0.01
                ],
                "value_change": ctx.valuation.mean(ctx.lines[fa_id], ctx.punt)
                - ctx.valuation.mean(ctx.lines[drop_id], ctx.punt),
            }
            if best is None or move["expected_wins_change"] > best["expected_wins_change"]:
                best = move
        if best is not None:
            moves.append(best)

    moves.sort(key=lambda m: (-m["expected_wins_change"], -m["value_change"]))
    return {
        "base": base_outlook,
        "drop_candidates": [ctx.snap.player_name(pid) for pid in droppable],
        "acquisitions_left": acquisitions_left,
        "moves": moves,
    }
