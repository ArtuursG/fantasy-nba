"""Advanced per-player stats from ESPN's box-score numbers.

Shooting efficiency (TS%, eFG%, 3P%), per-36 rates, assist-to-turnover,
offensive and defensive rebounds, double-double rate, how many of his
team's games he has played, and game-to-game consistency: each recent
game scored on the same 9-cat value scale as the rankings, then the
average, spread, floor and ceiling of those values.
"""

from __future__ import annotations

from statistics import fmean, pstdev

from fantasy.analysis.context import Context
from fantasy.analysis.stats import played_games
from fantasy.models import Game, Player, StatLine
from fantasy.timeutil import parse_iso

CONSISTENCY_GAMES = 15
PER36 = ("pts", "reb", "ast", "stl", "blk", "tpm", "to")
DOUBLE_DIGIT = ("pts", "reb", "ast", "stl", "blk")


def _ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def double_double(game: Game) -> bool:
    return sum(1 for name in DOUBLE_DIGIT if getattr(game.line, name) >= 10) >= 2


def shooting(line: StatLine) -> dict:
    return {
        "ts_pct": _round(_ratio(line.pts, 2 * (line.fga + 0.44 * line.fta)), 3),
        "efg_pct": _round(_ratio(line.fgm + 0.5 * line.tpm, line.fga), 3),
        "tp_pct": _round(_ratio(line.tpm, line.tpa), 3),
        "tpa": _round(line.tpa),
        "ft_rate": _round(_ratio(line.fta, line.fga), 2),
    }


def advanced_stats(ctx: Context, player: Player) -> dict | None:
    season = player.stats.get("season")
    line = season if season is not None and season.gp > 0 else ctx.lines.get(player.id)
    if line is None or line.min <= 0:
        return None
    recent = played_games(player)[-CONSISTENCY_GAMES:]
    values = [ctx.valuation.mean(g.line, ctx.punt) for g in recent]

    team_games = None
    if season is not None and season.gp > 0 and player.pro_team_id:
        cutoff = ctx.now
        team_games = sum(
            1
            for g in ctx.calendar.by_team.get(player.pro_team_id, [])
            if g.sp >= ctx.snap.league.first_scoring_period and parse_iso(g.start) <= cutoff
        )

    return {
        "source": "season" if line is season else "projection",
        **shooting(line),
        "ast_to": _round(_ratio(line.ast, line.to), 2),
        "oreb": _round(line.oreb),
        "dreb": _round(line.dreb),
        "stocks": _round(line.stl + line.blk),
        "per36": (
            {name: round(getattr(line, name) * 36 / line.min, 1) for name in PER36}
            if line.min >= 5
            else None
        ),
        "dd_rate": _round(_ratio(sum(1 for g in recent if double_double(g)), len(recent)), 2),
        "games_played": int(season.gp) if season is not None else 0,
        "team_games": team_games,
        "played_share": (
            _round(min(1.0, season.gp / team_games), 2)
            if team_games and season is not None
            else None
        ),
        "consistency": (
            {
                "games": len(values),
                "mean": round(fmean(values), 2),
                "sd": round(pstdev(values), 2),
                "floor": round(_percentile(values, 0.2), 2),
                "ceiling": round(_percentile(values, 0.8), 2),
                "bad_games": round(sum(1 for v in values if v < -0.5) / len(values), 2),
            }
            if len(values) >= 3
            else None
        ),
    }
