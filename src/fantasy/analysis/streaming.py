"""How much an opponent is likely to stream for the rest of a matchup.

The forecast otherwise assumes a roster stays as it is. A team with
acquisitions left that usually uses them will add players who fill its
open lineup slots. Expected adds come from the team's own pace in finished
matchups (the league's when it has none yet, an assumption before anyone
has a finished week), capped by what it has left, and scaled by how much
of the matchup remains. Each add brings the games a typical good free
agent has on the days that team has a free slot, at the typical
streamer's per-game line.
"""

from __future__ import annotations

from dataclasses import dataclass

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import SideProjection
from fantasy.analysis.schedule import game_started
from fantasy.analysis.strategy import typical_streamer
from fantasy.models import COUNTING_FIELDS, Team

ASSUMED_WEEKLY_ADDS = 2.0
STREAMER_POOL = 15


@dataclass
class Streaming:
    acquisitions_left: int
    weekly_rate: float
    basis: str
    expected_adds: float
    games_per_add: float
    games: float

    def to_dict(self) -> dict:
        return {
            "acquisitions_left": self.acquisitions_left,
            "weekly_rate": round(self.weekly_rate, 1),
            "basis": self.basis,
            "expected_adds": round(self.expected_adds, 1),
            "games_per_add": round(self.games_per_add, 1),
            "games": round(self.games, 1),
        }


def weekly_rate(ctx: Context, team: Team) -> tuple[float, str]:
    """Acquisitions per matchup in finished matchups: the team's own pace,
    else the league's, else an assumption."""
    current = ctx.snap.league.matchup_period

    def finished(t: Team) -> list[int]:
        return [n for period, n in t.matchup_acquisitions.items() if period < current]

    own = finished(team)
    if own:
        return sum(own) / len(own), "own pace"
    league = [n for t in ctx.snap.teams for n in finished(t)]
    if league:
        return sum(league) / len(league), "league pace"
    return ASSUMED_WEEKLY_ADDS, "assumed"


def expected_streaming(
    ctx: Context, side: SideProjection, acquisitions_left: int, free_agent_ids: list[int]
) -> Streaming:
    rate, basis = weekly_rate(ctx, side.team)
    days = [sp for sp in ctx.sps if ctx.calendar.by_sp.get(sp)]
    left_days = {p.sp for p in side.remaining_plans}
    share = len([sp for sp in days if sp in left_days]) / len(days) if days else 0.0
    adds = min(float(acquisitions_left), rate * share)

    open_days = {p.sp for p in side.remaining_plans if p.open_slots}
    slot_days = sum(len(p.open_slots) for p in side.remaining_plans)
    fits = []
    for pid in free_agent_ids[:STREAMER_POOL]:
        player = ctx.snap.players.get(pid)
        if player is None or not player.pro_team_id:
            continue
        games = ctx.calendar.team_games(player.pro_team_id, ctx.sps)
        fits.append(sum(1 for g in games if g.sp in open_days and not game_started(g, ctx.now)))
    per_add = sum(fits) / len(fits) if fits else 0.0
    return Streaming(
        acquisitions_left=acquisitions_left,
        weekly_rate=rate,
        basis=basis,
        expected_adds=adds,
        games_per_add=per_add,
        games=min(adds * per_add, float(slot_days)),
    )


def apply_streaming(
    ctx: Context, side: SideProjection, streaming: Streaming, free_agent_ids: list[int]
) -> None:
    """Add the expected streamed games to the side's remaining totals."""
    if streaming.games <= 0:
        return
    line = typical_streamer(ctx, free_agent_ids)
    for name in COUNTING_FIELDS:
        side.remaining[name] = side.remaining.get(name, 0.0) + getattr(line, name) * streaming.games
    side.stream_games = streaming.games
