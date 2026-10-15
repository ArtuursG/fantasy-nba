"""NBA calendar, daily lineups and usable games.

A game only counts in head-to-head if the player is in a starting slot that
day. Each day the roster's players with a game are slotted best-first into
PG, SG, SF, PF, C, G, F, UTIL x3 (a bipartite matching, so a player who
could fill several slots never blocks one who fits only one); whoever finds
no slot is benched and that game is lost. A free agent's usable games are
the days he would still find an open slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fantasy.espn.constants import (
    IR_SLOT,
    NON_STARTING_SLOTS,
    POSITION_SLOTS,
    UNAVAILABLE_STATUSES,
)
from fantasy.models import Player, ProGame, Snapshot, Team
from fantasy.timeutil import date_for_sp, parse_iso, sp_dates_from

LOW_VOLUME_MAX = 5
HIGH_VOLUME_MIN = 10
UTIL_SLOT = 11
# Slots a player can fill when ESPN gave no eligibility list.
POSITION_DEFAULT_SLOTS = {
    "PG": {0, 5},
    "SG": {1, 5},
    "SF": {2, 6},
    "PF": {3, 6},
    "C": {4},
}


@dataclass
class Calendar:
    games: list[ProGame]
    sp_dates: dict[int, date]
    by_sp: dict[int, list[ProGame]] = field(default_factory=dict)
    by_team: dict[int, list[ProGame]] = field(default_factory=dict)

    @classmethod
    def build(cls, snapshot: Snapshot) -> Calendar:
        calendar = cls(
            games=snapshot.pro_games,
            sp_dates=sp_dates_from((g.sp, g.date) for g in snapshot.pro_games),
        )
        for game in snapshot.pro_games:
            calendar.by_sp.setdefault(game.sp, []).append(game)
            calendar.by_team.setdefault(game.home_id, []).append(game)
            calendar.by_team.setdefault(game.away_id, []).append(game)
        return calendar

    def date_of(self, sp: int) -> date | None:
        return date_for_sp(self.sp_dates, sp)

    def team_games(self, team_id: int, sps: list[int]) -> list[ProGame]:
        wanted = set(sps)
        return [g for g in self.by_team.get(team_id, []) if g.sp in wanted]


def matchup_sps(snapshot: Snapshot, period: int | None = None) -> list[int]:
    league = snapshot.league
    sps = league.matchup_periods.get(period or league.matchup_period)
    if sps:
        return sorted(sps)
    # No schedule settings: treat the next seven days as the matchup.
    return list(range(league.scoring_period, league.scoring_period + 7))


def is_available(player: Player, day: date) -> bool:
    if player.injury_status not in UNAVAILABLE_STATUSES:
        return True
    return bool(player.expected_return) and date.fromisoformat(player.expected_return) <= day


def starting_slots(lineup_slots: dict[int, int]) -> list[int]:
    """Slot instances, specific ones first and UTIL last."""
    order = sorted(
        (s for s, n in lineup_slots.items() if s not in NON_STARTING_SLOTS and n > 0),
        key=lambda s: (s == UTIL_SLOT, s),
    )
    return [slot for slot in order for _ in range(lineup_slots[slot])]


def eligible_starting_slots(player: Player) -> set[int]:
    slots = {s for s in player.eligible_slots if s not in NON_STARTING_SLOTS}
    if not slots:
        slots = set(POSITION_DEFAULT_SLOTS.get(player.default_position, set()))
        if slots:
            slots.add(UTIL_SLOT)
    elif any(s in slots for s in POSITION_SLOTS):
        slots.add(UTIL_SLOT)
    return slots


def positions(player: Player) -> list[str]:
    """Real positions (PG..C) from ESPN eligibility, default position as fallback."""
    names = ["PG", "SG", "SF", "PF", "C"]
    found = [names[s] for s in POSITION_SLOTS if s in player.eligible_slots]
    if not found and player.default_position:
        found = [player.default_position]
    return found


class Lineup:
    """Players matched to starting slot instances (Kuhn's augmenting paths)."""

    def __init__(self, slots: list[int]) -> None:
        self.slots = slots
        self.match: list[int | None] = [None] * len(slots)
        self.eligible: dict[int, set[int]] = {}

    def try_add(self, player_id: int, eligible: set[int]) -> bool:
        self.eligible[player_id] = eligible
        if self._augment(player_id, set()):
            return True
        del self.eligible[player_id]
        return False

    def _augment(self, player_id: int, seen: set[int]) -> bool:
        for i, slot in enumerate(self.slots):
            if slot in self.eligible[player_id] and i not in seen:
                seen.add(i)
                current = self.match[i]
                if current is None or self._augment(current, seen):
                    self.match[i] = player_id
                    return True
        return False

    def fits(self, player_id: int, eligible: set[int]) -> bool:
        trial = Lineup(self.slots)
        trial.match = list(self.match)
        trial.eligible = dict(self.eligible)
        return trial.try_add(player_id, eligible)

    @property
    def started(self) -> list[int]:
        return [p for p in self.match if p is not None]

    @property
    def open_slots(self) -> list[int]:
        return [s for s, p in zip(self.slots, self.match, strict=True) if p is None]


@dataclass
class DayPlan:
    sp: int
    date: date
    nba_games: int
    playing: list[int]
    started: list[int]
    benched: list[int]
    unavailable: list[int]
    open_slots: list[int]
    lineup: Lineup

    @property
    def volume(self) -> str:
        if self.nba_games <= LOW_VOLUME_MAX:
            return "low"
        if self.nba_games >= HIGH_VOLUME_MIN:
            return "high"
        return "normal"


def game_started(game: ProGame, now: datetime) -> bool:
    return parse_iso(game.start) <= now


def plan_days(
    calendar: Calendar,
    snapshot: Snapshot,
    team: Team,
    values: dict[int, float],
    sps: list[int],
    now: datetime,
    *,
    remaining: bool = True,
    available_from: dict[int, date] | None = None,
) -> list[DayPlan]:
    """Best lineup per day: remaining games (tip-off after `now`) or, with
    remaining=False, games already played. `available_from` holds players
    back until a date (a waiver claim that hasn't cleared yet)."""
    available_from = available_from or {}
    slots = starting_slots(snapshot.league.lineup_slots)
    roster = [
        snapshot.players[s.player_id]
        for s in team.roster
        if s.slot_id != IR_SLOT and s.player_id in snapshot.players
    ]
    plans = []
    for sp in sps:
        day = calendar.date_of(sp)
        all_games = calendar.by_sp.get(sp, [])
        games = [g for g in all_games if game_started(g, now) != remaining]
        if day is None or not games:
            continue
        teams_playing = {g.home_id for g in games} | {g.away_id for g in games}
        playing = [
            p
            for p in roster
            if p.pro_team_id in teams_playing and day >= available_from.get(p.id, day)
        ]
        available = [p for p in playing if is_available(p, day)]
        lineup = Lineup(slots)
        started, benched = [], []
        for player in sorted(available, key=lambda p: values.get(p.id, 0.0), reverse=True):
            if lineup.try_add(player.id, eligible_starting_slots(player)):
                started.append(player.id)
            else:
                benched.append(player.id)
        plans.append(
            DayPlan(
                sp=sp,
                date=day,
                nba_games=len(all_games),
                playing=[p.id for p in available],
                started=started,
                benched=benched,
                unavailable=[p.id for p in playing if p not in available],
                open_slots=lineup.open_slots,
                lineup=lineup,
            )
        )
    return plans


def candidate_days(
    player: Player, plans: list[DayPlan], calendar: Calendar, now: datetime
) -> tuple[list[DayPlan], list[DayPlan]]:
    """(days the player has a remaining game, days he'd also find an open slot)."""
    with_game, usable = [], []
    eligible = eligible_starting_slots(player)
    for plan in plans:
        games = [
            g
            for g in calendar.by_sp.get(plan.sp, [])
            if player.pro_team_id in (g.home_id, g.away_id) and not game_started(g, now)
        ]
        if not games:
            continue
        with_game.append(plan)
        if is_available(player, plan.date) and plan.lineup.fits(player.id, eligible):
            usable.append(plan)
    return with_game, usable


def back_to_backs(days: list[date]) -> int:
    ordered = sorted(set(days))
    return sum(1 for a, b in zip(ordered, ordered[1:], strict=False) if b - a == timedelta(days=1))
