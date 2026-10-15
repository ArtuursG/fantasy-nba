"""This matchup's category strategy and next matchup's preview.

Strategy: for each category, how much one extra game from a typical
streamer moves the odds of winning it (its leverage). Categories in reach
with the most leverage are the ones to chase with streams and lineup
choices; near-certain ones are locked, hopeless ones conceded, and those
narrowly ahead are protected. Turnovers rise with every game streamed, so
their leverage is negative.

Preview: next matchup's opponent, both rosters' games and usable games,
each day's NBA volume and open slots, and the category odds from the two
rosters' projections.
"""

from __future__ import annotations

import math
from statistics import median

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import (
    SideProjection,
    category_outlook,
    day_rows,
    matchup_outlook,
    project_side,
)
from fantasy.analysis.stats import CAT_FIELDS, PCT_FIELDS, REVERSE_CATS
from fantasy.models import COUNTING_FIELDS, StatLine
from fantasy.timeutil import day_label

STREAMER_POOL = 30
LOCKED = 0.9
CONCEDE = 0.1


def typical_streamer(ctx: Context, free_agent_ids: list[int]) -> StatLine:
    """Median per-game line of the best free agents still available."""
    lines = [ctx.lines[pid] for pid in free_agent_ids[:STREAMER_POOL] if ctx.lines[pid].min > 0]
    line = StatLine(gp=1)
    if lines:
        for name in COUNTING_FIELDS:
            setattr(line, name, median(getattr(x, name) for x in lines))
    return line


def _density(edge: float, sd: float) -> float:
    z = edge / sd
    return math.exp(-z * z / 2) / (math.sqrt(2 * math.pi) * sd)


def leverage(row: dict, streamer: StatLine) -> float:
    """Change in the chance of winning the category from one more game of
    the typical streamer."""
    if row["edge"] is None or row["sd"] <= 0:
        return 0.0
    cat = row["cat"]
    if cat in PCT_FIELDS:
        made, attempted = PCT_FIELDS[cat]
        if row["my_attempts"] <= 0 or row["me"] is None:
            return 0.0
        shift = (getattr(streamer, made) - row["me"] * getattr(streamer, attempted)) / row[
            "my_attempts"
        ]
    else:
        shift = getattr(streamer, CAT_FIELDS[cat])
        if cat in REVERSE_CATS:
            shift = -shift
    return _density(row["edge"], row["sd"]) * shift


def category_strategy(ctx: Context, projected: list[dict], free_agent_ids: list[int]) -> dict:
    streamer = typical_streamer(ctx, free_agent_ids)
    rows = []
    for row in projected:
        lev = leverage(row, streamer)
        p = row["p_win"]
        if row["cat"] in ctx.punt:
            plan = "Punted"
        elif p >= LOCKED:
            plan = "Locked"
        elif p <= CONCEDE:
            plan = "Concede"
        elif p >= 0.7:
            plan = "Protect"
        elif lev > 0:
            plan = "Chase"
        else:
            plan = "Hold"  # streaming makes it worse (turnovers): win it with the lineup
        rows.append({"cat": row["cat"], "p_win": p, "leverage": lev, "plan": plan})
    chase = sorted((r for r in rows if r["plan"] == "Chase"), key=lambda r: -r["leverage"])

    fits = []
    focus = [r["cat"] for r in chase]
    if focus:
        weight = {r["cat"]: r["leverage"] for r in chase}
        for pid in free_agent_ids[:STREAMER_POOL]:
            z = ctx.valuation.by_cat(ctx.lines[pid])
            score = sum(weight[c] * z.get(c, 0.0) for c in focus)
            fits.append(
                {
                    "id": pid,
                    "name": ctx.snap.players[pid].name,
                    "pro_team": ctx.snap.players[pid].pro_team,
                    "score": score,
                    "helps": [c for c in focus if z.get(c, 0.0) >= 0.5],
                }
            )
        fits.sort(key=lambda f: -f["score"])
    return {
        "categories": rows,
        "chase": focus,
        "protect": [r["cat"] for r in rows if r["plan"] == "Protect"],
        "concede": [r["cat"] for r in rows if r["plan"] == "Concede"],
        "locked": [r["cat"] for r in rows if r["plan"] == "Locked"],
        "hold": [r["cat"] for r in rows if r["plan"] == "Hold"],
        "punted": [r["cat"] for r in rows if r["plan"] == "Punted"],
        "best_fits": [f for f in fits if f["score"] > 0][:5],
    }


def next_matchup(ctx: Context, strength: dict[int, dict]) -> dict | None:
    league = ctx.snap.league
    period = league.matchup_period + 1
    sps = league.matchup_periods.get(period)
    me = ctx.my_team
    if not sps or me is None:
        return None
    opp_id = ctx.opponent_id(me.id, period)
    opp = ctx.snap.team(opp_id)
    if opp is None:
        return None
    zero = dict.fromkeys(COUNTING_FIELDS, 0.0)
    mine: SideProjection = project_side(ctx, me, None, elapsed=zero, sps=sorted(sps))
    theirs = project_side(ctx, opp, None, elapsed=zero, sps=sorted(sps))
    projected = [
        o for c in league.categories if (o := category_outlook(c, mine, theirs)) is not None
    ]
    first, last = ctx.calendar.date_of(min(sps)), ctx.calendar.date_of(max(sps))
    days = day_rows(mine.remaining_plans, theirs.remaining_plans, ctx)
    my_strength, opp_strength = strength.get(me.id, {}), strength.get(opp.id, {})
    return {
        "period": period,
        "dates": [day_label(first) if first else "", day_label(last) if last else ""],
        "opponent": opp.name,
        "opponent_record": f"{opp.wins}-{opp.losses}-{opp.ties}",
        "outlook": matchup_outlook(projected),
        "projected": [
            {
                "cat": o["cat"],
                "me": o["me"],
                "opp": o["opp"],
                "p_win": o["p_win"],
                "call": o["call"],
            }
            for o in projected
        ],
        "games": {
            "me": {
                "scheduled": mine.scheduled_remaining,
                "usable": mine.usable_remaining,
            },
            "opp": {
                "scheduled": theirs.scheduled_remaining,
                "usable": theirs.usable_remaining,
            },
        },
        "days": days,
        "ranks": {
            cat: {
                "me": my_strength.get("ranks", {}).get(cat),
                "opp": opp_strength.get("ranks", {}).get(cat),
            }
            for cat in league.categories
        },
    }
