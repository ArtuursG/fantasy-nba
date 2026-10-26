"""Free agents ranked by how interesting they are right now.

ESPN's rank orders by season value. This ranking starts from the same kind
of value (9-cat z-score of the projection line) and adds what a manager
acts on: how widely he is rostered across ESPN (the market's view), recent
form, a minutes jump, a new starting job, an injured teammate, a return
from injury, the add rate, and how many games he could actually start for
this roster before the matchup ends (a small part: streaming has its own
list).
"""

from __future__ import annotations

from datetime import date, timedelta

from fantasy.analysis.context import Context
from fantasy.analysis.roles import RoleInfo
from fantasy.analysis.schedule import DayPlan, candidate_days
from fantasy.analysis.stats import average
from fantasy.espn.constants import C_SLOT, UNAVAILABLE_STATUSES
from fantasy.timeutil import day_label

RETURN_SOON = timedelta(days=3)
# Last-5 value this far (in summed z-scores) from the projection is hot/cold.
HOT = 2.5
STRONG_Z = 0.75
# Rostered share across ESPN leagues is the market's view of a player's
# rest-of-season worth; it counts above or below this share.
MARKET_PIVOT = 25.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _out_for_now(status: str, expected_return: str | None, today: date) -> bool:
    if status not in UNAVAILABLE_STATUSES:
        return False
    return not (expected_return and date.fromisoformat(expected_return) <= today + RETURN_SOON)


def rank_free_agents(
    ctx: Context,
    roles: dict[int, RoleInfo],
    opps: dict[int, list[dict]],
    my_plans: list[DayPlan],
    my_c_count: int,
) -> list[dict]:
    today = ctx.now.date()
    c_limit = ctx.snap.league.c_limit
    rows = []
    for player_id in ctx.snap.free_agent_ids:
        player = ctx.snap.players[player_id]
        info = roles[player_id]
        value = ctx.values.get(player_id, 0.0)
        form = 0.0
        if len(info.last5) >= 3:
            # Three games say less than five.
            form = _clamp(ctx.valuation.score(average(info.last5)) - value, -4, 4)
            form *= len(info.last5) / 5
        with_game, usable = candidate_days(player, my_plans, ctx.calendar, ctx.now)
        out = _out_for_now(player.injury_status, player.expected_return, today)
        c_capped = C_SLOT in player.eligible_slots and my_c_count >= c_limit

        score = (
            value
            + 0.25 * form
            + 0.12 * _clamp(info.min_delta or 0.0, -10, 10)
            + (1.0 if info.new_starter else 0.0)
            + (0.8 if opps.get(player_id) else 0.0)
            + (0.5 if info.returned else 0.0)
            + 0.06 * _clamp(player.percent_change or 0.0, -10, 25)
            + 0.04 * _clamp((player.percent_owned or 0.0) - MARKET_PIVOT, -25, 50)
            + 0.15 * len(usable)
            - (4.0 if out else 0.0)
            - (0.5 if player.injury_status in ("DAY_TO_DAY", "QUESTIONABLE") else 0.0)
            - (0.3 if c_capped else 0.0)
        )

        reasons = []
        if info.trend == "UP" and info.min_delta is not None:
            reasons.append(
                f"Minutes UP {info.min_delta:+.1f} (last 5: {info.recent_min:.0f} vs "
                f"{info.baseline_min:.0f})"
            )
        if info.new_starter:
            reasons.append(f"New starter ({info.starts_last5} of last {len(info.last5)})")
        for item in opps.get(player_id, []):
            reasons.append(f"Opportunity: {item['player']} out (+{item['bump']:.0f} MIN est.)")
        if info.returned:
            reasons.append(f"Back from injury ({info.returned[0]} games missed)")
        if (player.percent_change or 0) >= 3:
            reasons.append(f"Add trend +{player.percent_change:.1f}%")
        if form >= HOT:
            reasons.append("Hot: last 5 well above his projection")
        elif form <= -HOT:
            reasons.append("Cold: last 5 well below his projection")
        if usable:
            days = ", ".join(day_label(p.date)[:3] for p in usable)
            reasons.append(f"{len(usable)} usable games left ({days})")
        # Few turnovers mostly means few minutes, so TO doesn't count as a
        # strength; punted categories don't either.
        strong = sorted(
            (
                (z, cat)
                for cat, z in ctx.valuation.by_cat(ctx.lines[player_id]).items()
                if z >= STRONG_Z and cat != "TO" and cat not in ctx.punt
            ),
            reverse=True,
        )[:3]
        if strong:
            reasons.append("Strong cats: " + ", ".join(cat for _, cat in strong))
        if info.no_prev_season and (info.trend == "UP" or info.new_starter):
            reasons.append("Likely rookie with a growing role")
        if out:
            reasons.append("OUT now")
        if c_capped:
            reasons.append(f"C-eligible: you already have {my_c_count} C (limit {c_limit})")

        rows.append(
            {
                "player_id": player_id,
                "score": round(score, 2),
                "reasons": reasons,
                "games_remaining": len(with_game),
                "usable": len(usable),
                "usable_days": [day_label(p.date) for p in usable],
                "game_days": [day_label(p.date) for p in with_game],
            }
        )
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows
