"""Free agents likely to be picked up soon, so worth grabbing first.

Signals: ESPN's add trend across all leagues, a new or bigger role
(minutes up, a starting spot, an injured teammate's minutes), and demand
in this league: how many other teams rank in the bottom part of the
categories he is good at.
"""

from __future__ import annotations

from fantasy.analysis.context import Context
from fantasy.analysis.roles import RoleInfo
from fantasy.analysis.schedule import positions
from fantasy.espn.constants import UNAVAILABLE_STATUSES

HOT_LIMIT = 10
STRONG_Z = 0.5
NEED_RANK = 7  # bottom four of ten
MIN_SCORE = 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def hot_free_agents(
    ctx: Context,
    roles: dict[int, RoleInfo],
    opps: dict[int, list[dict]],
    strength: dict[int, dict],
) -> list[dict]:
    snap = ctx.snap
    needs = {
        team.id: {cat for cat, rank in strength[team.id]["ranks"].items() if rank >= NEED_RANK}
        for team in snap.teams
        if team.id != snap.my_team_id and team.id in strength
    }
    names = {t.id: t.name for t in snap.teams}
    rows = []
    for pid in snap.free_agent_ids:
        player = snap.players.get(pid)
        if player is None or player.injury_status in UNAVAILABLE_STATUSES or pid not in ctx.lines:
            continue
        info = roles[pid]
        z = ctx.valuation.by_cat(ctx.lines[pid])
        strong = {cat for cat, value in z.items() if value >= STRONG_Z}
        demand = [tid for tid, cats in needs.items() if strong & cats]
        trend = player.percent_change or 0.0
        value = ctx.valuation.mean(ctx.lines[pid], ctx.punt)
        signals = []
        if trend >= 1:
            signals.append(f"added in {trend:+.1f}% more ESPN leagues")
        if info.new_starter:
            signals.append("new starter")
        if info.trend == "UP" and info.min_delta:
            signals.append(f"minutes {info.min_delta:+.1f}")
        if opps.get(pid):
            signals.append("injured teammate's minutes")
        if demand:
            signals.append(f"{len(demand)} teams need his categories")
        score = (
            0.08 * _clamp(trend, -5, 25)
            + (1.0 if info.new_starter else 0.0)
            + 0.05 * _clamp(info.min_delta or 0.0, -10, 10)
            + (0.6 if opps.get(pid) else 0.0)
            + 0.15 * len(demand)
            + 0.8 * max(value, 0.0)
        )
        if score < MIN_SCORE or not signals:
            continue
        rows.append(
            {
                "id": pid,
                "name": player.name,
                "pro_team": player.pro_team,
                "positions": "/".join(positions(player)),
                "health": player.injury_status,
                "roster_pct": round(player.percent_owned, 1)
                if player.percent_owned is not None
                else None,
                "add_trend": round(trend, 1),
                "value": round(value, 2),
                "strong": sorted(strong),
                "demand": [names[tid] for tid in demand],
                "signals": signals,
                "score": round(score, 2),
                "likelihood": "high" if score >= 2.5 else "medium" if score >= 1.6 else "some",
            }
        )
    rows.sort(key=lambda r: -r["score"])
    return rows[:HOT_LIMIT]
