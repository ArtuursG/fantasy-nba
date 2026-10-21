"""The matchup week as a grid: my players down the side, the days across.

Each cell says what that player's game means for me: started (or will),
started but doubtful, on the bench for want of a slot, out, or already
played. The day columns carry the NBA volume and my open slots, which is
what decides when a pickup is worth it.
"""

from __future__ import annotations

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import DayPlan, plan_days, positions
from fantasy.espn.constants import IR_SLOT, UNAVAILABLE_STATUSES
from fantasy.models import Team
from fantasy.timeutil import day_label


def _plans(ctx: Context, team: Team) -> tuple[dict[int, DayPlan], dict[int, DayPlan]]:
    args = (ctx.calendar, ctx.snap, team, ctx.values, ctx.sps, ctx.now)
    return (
        {p.sp: p for p in plan_days(*args, remaining=False)},
        {p.sp: p for p in plan_days(*args)},
    )


def week_grid(ctx: Context, team: Team, opponent: Team | None = None) -> dict:
    played, ahead = _plans(ctx, team)
    opp_played, opp_ahead = _plans(ctx, opponent) if opponent else ({}, {})
    snap = ctx.snap
    days = []
    for sp in ctx.sps:
        day = ctx.calendar.date_of(sp)
        if day is None:
            continue
        games = ctx.calendar.by_sp.get(sp, [])
        future = ahead.get(sp)
        past = played.get(sp)
        days.append(
            {
                "sp": sp,
                "label": day_label(day),
                "nba_games": len(games),
                "past": future is None and past is not None,
                "starts": len(future.started if future else []) + len(past.started if past else []),
                "open_slots": len(future.open_slots) if future else None,
                "opp_starts": sum(
                    len(p.started) for p in (opp_ahead.get(sp), opp_played.get(sp)) if p
                ),
            }
        )

    rows = []
    for spot in sorted(
        team.roster, key=lambda s: (s.slot_id == IR_SLOT, -ctx.values.get(s.player_id, 0))
    ):
        player = snap.players.get(spot.player_id)
        if player is None:
            continue
        cells = {}
        for day in days:
            sp = day["sp"]
            game = next(
                (
                    g
                    for g in ctx.calendar.by_sp.get(sp, [])
                    if player.pro_team_id in (g.home_id, g.away_id)
                ),
                None,
            )
            if game is None:
                continue
            home = game.home_id == player.pro_team_id
            other = game.away_id if home else game.home_id
            vs = ("" if home else "@") + snap.pro_teams.get(other, "?")
            cells[str(sp)] = {
                "vs": vs,
                "kind": _kind(ctx, player.id, spot.slot_id, sp, played, ahead),
            }
        rows.append(
            {
                "id": player.id,
                "name": player.name,
                "positions": "/".join(positions(player)),
                "health": player.injury_status,
                "ir": spot.slot_id == IR_SLOT,
                "games": len(cells),
                "starts": sum(
                    1 for c in cells.values() if c["kind"] in ("start", "doubt", "played")
                ),
                "cells": cells,
            }
        )
    return {"days": days, "players": rows}


def _kind(
    ctx: Context,
    pid: int,
    slot_id: int,
    sp: int,
    played: dict[int, DayPlan],
    ahead: dict[int, DayPlan],
) -> str:
    plan = ahead.get(sp)
    if plan is not None:
        if pid in plan.started:
            chance = plan.chance.get(pid, 1.0)
            if chance >= 1.0:
                return "start"
            healthy = ctx.snap.players[pid].injury_status in ("ACTIVE", "NORMAL")
            return "rest" if pid in plan.rest and healthy else "doubt"
        if pid in plan.benched:
            return "bench"
        if pid in plan.unavailable or slot_id == IR_SLOT:
            return "out"
    past = played.get(sp)
    if past is not None:
        player = ctx.snap.players[pid]
        if any(g.sp == sp and g.played for g in player.games):
            return "played"
        return "missed"
    player = ctx.snap.players[pid]
    return "out" if player.injury_status in UNAVAILABLE_STATUSES else "bench"


IDEAS_PER_DAY = 2
MIN_IDEA_GAIN = 0.05


def add_pickup_ideas(ctx: Context, grid: dict, whatif: dict | None) -> None:
    """For each day ahead with an open slot: the free agents who play that
    day and help the matchup most (best drop for each), from the what-if."""
    if not whatif:
        return
    base = whatif["base"]["expected_wins"]
    drops = [d["id"] for d in whatif["drops"]]
    best: dict[int, tuple[float, float, int]] = {}
    for add in whatif["adds"]:
        scored = [
            (row[1] - base, row[0], drop)
            for drop in drops
            if (row := whatif["results"].get(f"{add['id']}:{drop}"))
        ]
        if scored:
            best[add["id"]] = max(scored)
    names = {a["id"]: a for a in whatif["adds"]}
    for day in grid["days"]:
        day["ideas"] = []
        if day["past"] or not day["open_slots"]:
            continue
        playing = []
        for pid, (gain, p_after, drop) in best.items():
            player = ctx.snap.players.get(pid)
            if gain < MIN_IDEA_GAIN or player is None or not player.pro_team_id:
                continue
            games = ctx.calendar.team_games(player.pro_team_id, ctx.sps)
            if any(g.sp == day["sp"] for g in games):
                left = sum(1 for g in games if g.sp >= day["sp"])
                playing.append((gain, pid, p_after, drop, left))
        for gain, pid, p_after, drop, left in sorted(playing, reverse=True)[:IDEAS_PER_DAY]:
            day["ideas"].append(
                {
                    "id": pid,
                    "name": names[pid]["name"],
                    "team": names[pid]["team"],
                    "gain": round(gain, 2),
                    "p_win_after": p_after,
                    "drop": ctx.snap.player_name(drop),
                    "games_from_day": left,
                }
            )
