"""How each manager runs a team: lineups and pickups.

From the lineups ESPN had each day (read for the last two weeks): games a
team lost by leaving a player who played on the bench while a starting
slot was empty or held by someone without a game. Position eligibility
is not checked, so this is an upper bound on what a better lineup gets.
"""

from __future__ import annotations

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import SideProjection
from fantasy.analysis.schedule import starting_slots
from fantasy.espn.constants import BENCH_SLOT, NON_STARTING_SLOTS
from fantasy.models import COUNTING_FIELDS, Snapshot
from fantasy.timeutil import EASTERN

MIN_DAYS = 3


def lineup_habits(ctx: Context, team_id: int, sps: list[int] | None = None) -> dict:
    """`sps` limits it to those days (one matchup)."""
    snap = ctx.snap
    slots = len(starting_slots(snap.league.lineup_slots))
    today = ctx.now.astimezone(EASTERN).date()
    lost = starts = days = 0
    wanted = set(sps) if sps is not None else None
    for sp in sorted(snap.lineups):
        if wanted is not None and sp not in wanted:
            continue
        day = ctx.calendar.date_of(sp)
        lineup = snap.lineups[sp].get(team_id)
        if day is None or day >= today or not lineup:
            continue
        games = ctx.calendar.by_sp.get(sp, [])
        if not games:
            continue
        playing = {g.home_id for g in games} | {g.away_id for g in games}
        starters = [pid for pid, slot in lineup.items() if slot not in NON_STARTING_SLOTS]
        bench = [pid for pid, slot in lineup.items() if slot == BENCH_SLOT]
        idle = slots - sum(1 for pid in starters if _team_plays(snap, pid, playing))
        lost += min(max(idle, 0), sum(1 for pid in bench if _played(snap, pid, sp)))
        starts += sum(1 for pid in starters if _played(snap, pid, sp))
        days += 1
    return {
        "days": days,
        "lost_games": lost,
        "lost_per_week": round(lost / days * 7, 1) if days else None,
        "waste_rate": round(lost / (lost + starts), 3)
        if days >= MIN_DAYS and lost + starts
        else 0.0,
    }


def _played(snap: Snapshot, pid: int, sp: int) -> bool:
    player = snap.players.get(pid)
    return bool(player) and any(g.sp == sp and g.played for g in player.games)


def _team_plays(snap: Snapshot, pid: int, playing: set[int]) -> bool:
    player = snap.players.get(pid)
    return bool(player) and player.pro_team_id in playing


def apply_lineup_waste(side: SideProjection, rate: float) -> None:
    """Take off the share of games this manager usually leaves on the bench."""
    if rate <= 0:
        return
    side.waste_games = side.expected_remaining * rate
    for name in COUNTING_FIELDS:
        if name in side.remaining:
            side.remaining[name] *= 1 - rate
