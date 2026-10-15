"""Normalised league snapshot.

ESPN's responses are parsed once into these dataclasses; everything after
that (analysis, report, history) reads only these, so a stored snapshot can
be compared with a later one even if the parser changes in between.
"""

from __future__ import annotations

import dataclasses
import functools
import types
import typing
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

COUNTING_FIELDS = (
    "min",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "tpm",
    "reb",
    "ast",
    "stl",
    "blk",
    "to",
    "pts",
)


@dataclass
class StatLine:
    """Per-game averages over `gp` games; `gs` counts starts in those games."""

    gp: float = 0.0
    gs: float = 0.0
    min: float = 0.0
    fgm: float = 0.0
    fga: float = 0.0
    ftm: float = 0.0
    fta: float = 0.0
    tpm: float = 0.0
    reb: float = 0.0
    ast: float = 0.0
    stl: float = 0.0
    blk: float = 0.0
    to: float = 0.0
    pts: float = 0.0


@dataclass
class Game:
    """One NBA game a player appeared in (a line with gp=1)."""

    sp: int
    date: str = ""
    team_id: int = 0
    line: StatLine = field(default_factory=StatLine)

    @property
    def started(self) -> bool:
        return self.line.gs > 0

    @property
    def played(self) -> bool:
        return self.line.min > 0 or self.line.gp > 0


@dataclass
class Rating:
    rank: int | None = None
    rating: float | None = None
    pos_rank: int | None = None


@dataclass
class Player:
    id: int
    name: str
    pro_team_id: int = 0
    pro_team: str = "FA"
    default_position: str = ""
    eligible_slots: list[int] = field(default_factory=list)
    injury_status: str = "ACTIVE"
    injury_note: str | None = None
    injury_date: str | None = None
    expected_return: str | None = None
    percent_owned: float | None = None
    percent_change: float | None = None
    percent_started: float | None = None
    draft_rank: int | None = None
    ratings: dict[str, Rating] = field(default_factory=dict)
    pool_status: str | None = None
    on_team_id: int | None = None
    waiver_clear: str | None = None
    waiver_clear_estimated: bool = False
    stats: dict[str, StatLine] = field(default_factory=dict)
    games: list[Game] = field(default_factory=list)


@dataclass
class RosterSpot:
    player_id: int
    slot_id: int
    acquisition_type: str | None = None
    acquisition_date: str | None = None


@dataclass
class Team:
    id: int
    name: str
    abbrev: str = ""
    owners: list[str] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    waiver_rank: int | None = None
    acquisitions_total: int | None = None
    matchup_acquisitions: dict[int, int] = field(default_factory=dict)
    roster: list[RosterSpot] = field(default_factory=list)


@dataclass
class MatchupSide:
    team_id: int
    stats: dict[str, float] = field(default_factory=dict)
    results: dict[str, str] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0
    ties: int = 0


@dataclass
class Matchup:
    period: int
    home: MatchupSide
    away: MatchupSide | None = None
    winner: str = "UNDECIDED"


@dataclass
class TransactionItem:
    type: str
    player_id: int
    from_team_id: int | None = None
    to_team_id: int | None = None


@dataclass
class Transaction:
    id: str
    type: str
    status: str
    ts: str | None = None
    sp: int | None = None
    team_id: int | None = None
    bid: float | None = None
    items: list[TransactionItem] = field(default_factory=list)


@dataclass
class ProGame:
    id: int
    sp: int
    start: str
    date: str
    home_id: int
    away_id: int


@dataclass
class League:
    id: int
    season: int
    name: str
    size: int
    categories: list[str]
    lineup_slots: dict[int, int]
    scoring_period: int
    matchup_period: int
    matchup_periods: dict[int, list[int]]
    first_scoring_period: int = 1
    final_scoring_period: int = 0
    matchup_acquisition_limit: int | None = None
    waiver_hours: int | None = None
    c_limit: int = 4
    scoring_type: str | None = None


@dataclass
class Snapshot:
    fetched_at: str
    league: League
    my_team_id: int | None
    teams: list[Team]
    players: dict[int, Player]
    free_agent_ids: list[int]
    matchups: list[Matchup]
    transactions: list[Transaction]
    pro_games: list[ProGame]
    pro_teams: dict[int, str]
    warnings: list[str] = field(default_factory=list)
    demo: bool = False
    schema: int = SCHEMA_VERSION

    def team(self, team_id: int | None) -> Team | None:
        return next((t for t in self.teams if t.id == team_id), None)

    def player_name(self, player_id: int) -> str:
        player = self.players.get(player_id)
        return player.name if player else f"Player {player_id}"


def to_dict(obj: Any) -> Any:
    return dataclasses.asdict(obj)


def from_dict[T](cls: type[T], data: dict[str, Any]) -> T:
    """Rebuild a dataclass tree from `to_dict` output after a JSON round trip.

    JSON turns int dict keys into strings and drops the classes; the type
    hints say what each field was, so this converts them back. Unknown keys
    are ignored and missing ones take the field default, which keeps older
    snapshots readable after a field is added.
    """
    hints = _field_types(cls)
    return cls(**{name: _convert(tp, data[name]) for name, tp in hints.items() if name in data})


@functools.cache
def _field_types(cls: type) -> dict[str, Any]:
    hints = typing.get_type_hints(cls)
    return {f.name: hints[f.name] for f in dataclasses.fields(cls)}


def _convert(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (types.UnionType, typing.Union):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _convert(args[0], value) if len(args) == 1 else value
    if origin is list:
        (item,) = typing.get_args(tp)
        return [_convert(item, v) for v in value]
    if origin is dict:
        key_tp, value_tp = typing.get_args(tp)
        return {_convert(key_tp, k): _convert(value_tp, v) for k, v in value.items()}
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value)  # type: ignore[arg-type]
    if tp is int:
        return int(value)
    if tp is float:
        return float(value)
    return value
