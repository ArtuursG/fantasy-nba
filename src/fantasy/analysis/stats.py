"""Stat lines, category values and a 9-cat player value (z-scores)."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean, pstdev

from fantasy.models import COUNTING_FIELDS, Game, Player, StatLine

CAT_FIELDS = {
    "3PM": "tpm",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TO": "to",
    "PTS": "pts",
}
PCT_FIELDS = {"FG%": ("fgm", "fga"), "FT%": ("ftm", "fta")}
REVERSE_CATS = {"TO"}

# How many games the projection (or last season) is worth against games
# actually played this season: after 10 games it's an even blend.
PRIOR_GAMES = 10
# Share of the projection given to the last 15 days, so a changed role
# shows up before the season average catches up.
RECENT_WEIGHT = 0.35
RECENT_MIN_GAMES = 3


def cat_value(line: StatLine, cat: str) -> float | None:
    if cat in PCT_FIELDS:
        made, attempted = PCT_FIELDS[cat]
        attempts = getattr(line, attempted)
        return getattr(line, made) / attempts if attempts > 0 else None
    name = CAT_FIELDS.get(cat)
    return getattr(line, name) if name else None


def mix(a: StatLine, b: StatLine, weight_a: float) -> StatLine:
    line = StatLine(gp=a.gp, gs=a.gs)
    for name in COUNTING_FIELDS:
        setattr(line, name, weight_a * getattr(a, name) + (1 - weight_a) * getattr(b, name))
    return line


def average(games: list[Game]) -> StatLine:
    if not games:
        return StatLine()
    line = StatLine(gp=len(games), gs=sum(1 for g in games if g.started))
    for name in COUNTING_FIELDS:
        setattr(line, name, sum(getattr(g.line, name) for g in games) / len(games))
    return line


def played_games(player: Player) -> list[Game]:
    return [g for g in player.games if g.played]


def last_games(player: Player, n: int = 5) -> list[Game]:
    return played_games(player)[-n:]


def _has_values(line: StatLine | None) -> bool:
    return line is not None and (line.min > 0 or line.pts > 0)


def projection_line(player: Player) -> StatLine:
    """Per-game expectation used for projections and player value.

    Season averages, pulled toward ESPN's projection (or last season) while
    the sample is small, then nudged toward the last 15 days.
    """
    season = player.stats.get("season")
    prior = player.stats.get("projected")
    if not _has_values(prior):
        prior = player.stats.get("prev_season")
    if season is not None and season.gp > 0 and _has_values(prior):
        assert prior is not None
        base = mix(season, prior, season.gp / (season.gp + PRIOR_GAMES))
    elif season is not None and season.gp > 0:
        base = season
    elif _has_values(prior):
        assert prior is not None
        base = prior
    else:
        return average(last_games(player, 10))

    recent = player.stats.get("last15")
    if recent is not None and recent.gp >= RECENT_MIN_GAMES:
        return mix(recent, base, RECENT_WEIGHT)
    return base


def usage_proxy(line: StatLine) -> float | None:
    """Possessions used per 36 minutes (FGA + 0.44 FTA + TO). ESPN doesn't
    publish usage rate; this tracks it closely enough to see role changes."""
    if line.min <= 0:
        return None
    return (line.fga + 0.44 * line.fta + line.to) / line.min * 36


@dataclass
class Valuation:
    """Z-score parameters from a player pool, able to score any line."""

    cats: list[str]
    params: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    @classmethod
    def from_pool(cls, lines: list[StatLine], cats: list[str]) -> Valuation:
        valuation = cls(cats=[c for c in cats if c in PCT_FIELDS or c in CAT_FIELDS])
        pool = [line for line in lines if line.min > 0]
        if not pool:
            return valuation
        for cat in valuation.cats:
            if cat in PCT_FIELDS:
                made, attempted = PCT_FIELDS[cat]
                total = sum(getattr(line, attempted) for line in pool)
                rate = sum(getattr(line, made) for line in pool) / total if total else 0.0
                values = [getattr(x, made) - rate * getattr(x, attempted) for x in pool]
            else:
                rate = 0.0
                values = [getattr(line, CAT_FIELDS[cat]) for line in pool]
            valuation.params[cat] = (rate, fmean(values), pstdev(values))
        return valuation

    def by_cat(self, line: StatLine) -> dict[str, float]:
        scores = {}
        for cat, (rate, mean, sd) in self.params.items():
            if cat in PCT_FIELDS:
                made, attempted = PCT_FIELDS[cat]
                value = getattr(line, made) - rate * getattr(line, attempted)
            else:
                value = getattr(line, CAT_FIELDS[cat])
            z = (value - mean) / sd if sd > 0 else 0.0
            scores[cat] = -z if cat in REVERSE_CATS else z
        return scores

    def score(self, line: StatLine, punt: tuple[str, ...] = ()) -> float:
        """Summed z-scores over the categories not punted."""
        counted = [c for c in self.params if c not in punt]
        if line.min <= 0 and line.pts <= 0:
            # No stats at all: one standard deviation below average everywhere.
            return -float(len(counted))
        scores = self.by_cat(line)
        return sum(scores[c] for c in counted)

    def mean(self, line: StatLine, punt: tuple[str, ...] = ()) -> float:
        """Average z-score per category: about +1 for a first-round player,
        0 at the edge of the rosterable pool."""
        counted = [c for c in self.params if c not in punt]
        return self.score(line, punt) / len(counted) if counted else 0.0
