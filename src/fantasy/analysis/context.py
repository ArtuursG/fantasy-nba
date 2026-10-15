"""Derived data every analysis step shares, computed once per snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fantasy.analysis.schedule import Calendar, matchup_sps
from fantasy.analysis.stats import Valuation, projection_line
from fantasy.models import Matchup, Player, Snapshot, StatLine, Team
from fantasy.timeutil import parse_iso

# Players in a value pool are those worth rostering; with fewer rostered
# than this (before the draft) the most owned players stand in.
MIN_POOL = 60


def value_pool(snap: Snapshot, lines: dict[int, StatLine]) -> list[int]:
    """Players z-scores are measured against: everyone rostered, or before
    the draft the most owned players, as many as the league rosters."""
    rostered = [s.player_id for t in snap.teams for s in t.roster if s.player_id in lines]
    if len(rostered) >= MIN_POOL:
        return rostered
    candidates = sorted(lines, key=lambda pid: snap.players[pid].percent_owned or 0.0, reverse=True)
    return candidates[: max(MIN_POOL, 13 * max(snap.league.size, 1))]


@dataclass
class Context:
    snap: Snapshot
    now: datetime
    calendar: Calendar
    sps: list[int]
    lines: dict[int, StatLine]
    valuation: Valuation
    values: dict[int, float]
    punt: tuple[str, ...] = ()

    @classmethod
    def build(cls, snap: Snapshot, punt: tuple[str, ...] = ()) -> Context:
        """`values` (used to order lineups and rank free agents) leave out
        punted categories; matchup odds still cover every category."""
        lines = {pid: projection_line(p) for pid, p in snap.players.items()}
        valuation = Valuation.from_pool(
            [lines[pid] for pid in value_pool(snap, lines)], snap.league.categories
        )
        return cls(
            snap=snap,
            now=parse_iso(snap.fetched_at),
            calendar=Calendar.build(snap),
            sps=matchup_sps(snap),
            lines=lines,
            valuation=valuation,
            values={pid: valuation.score(line, punt) for pid, line in lines.items()},
            punt=punt,
        )

    @property
    def my_team(self) -> Team | None:
        return self.snap.team(self.snap.my_team_id)

    def matchup_for(self, team_id: int | None) -> Matchup | None:
        for matchup in self.snap.matchups:
            sides = [matchup.home.team_id, matchup.away.team_id if matchup.away else None]
            if team_id in sides:
                return matchup
        return None

    def opponent_id(self, team_id: int | None) -> int | None:
        matchup = self.matchup_for(team_id)
        if matchup is None or matchup.away is None:
            return None
        return matchup.away.team_id if matchup.home.team_id == team_id else matchup.home.team_id

    def roster_players(self, team: Team) -> list[Player]:
        return [
            self.snap.players[s.player_id] for s in team.roster if s.player_id in self.snap.players
        ]

    def owner_label(self, player: Player) -> str:
        team_id = player.on_team_id if player.pool_status == "ONTEAM" else None
        if team_id is None:
            return "WA" if player.pool_status == "WAIVERS" else "FA"
        if team_id == self.snap.my_team_id:
            return "MY TEAM"
        team = self.snap.team(team_id)
        name = team.name if team else f"Team {team_id}"
        if team_id == self.opponent_id(self.snap.my_team_id):
            return f"OPPONENT ({name})"
        return name
