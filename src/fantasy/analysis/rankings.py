"""Player rankings for this league's categories.

Each category value is a per-game z-score against the pool of rostered
players (percentages weighted by attempts, turnovers counted against). The
league value is their average over every category; the punt value averages
only the categories not punted, and players are ranked by it. Rankings exist
for each date range ESPN reports (full season, last 30/15/7 days) and for the
projection line.
"""

from __future__ import annotations

from statistics import fmean

from fantasy.analysis.context import Context, value_pool
from fantasy.analysis.schedule import positions
from fantasy.analysis.stats import Valuation, usage_proxy
from fantasy.models import Player, StatLine

RANGES = [
    ("season", "Full season"),
    ("last30", "Last 30 days"),
    ("last15", "Last 15 days"),
    ("last7", "Last 7 days"),
    ("projection", "Projection"),
]
INJURY_SHORT = {
    "OUT": "OUT",
    "INJURY_RESERVE": "OUT",
    "SUSPENSION": "SSPD",
    "DAY_TO_DAY": "DTD",
    "QUESTIONABLE": "Q",
    "DOUBTFUL": "D",
    "PROBABLE": "P",
}
# A range ranks players once most of the rostered pool has this many games.
SEASON_READY_GAMES = 5


def range_line(ctx: Context, player: Player, key: str) -> StatLine | None:
    if key == "projection":
        line = ctx.lines.get(player.id)
        return line if line is not None and line.min > 0 else None
    line = player.stats.get(key)
    return line if line is not None and line.gp > 0 and line.min > 0 else None


def default_range(ctx: Context) -> str:
    """Full season once the rostered players have played enough, before that
    the projection line."""
    rostered = [ctx.snap.players[s.player_id] for t in ctx.snap.teams for s in t.roster]
    games = sorted(
        (p.stats["season"].gp if "season" in p.stats else 0) for p in rostered if p is not None
    )
    if games and games[len(games) // 2] >= SEASON_READY_GAMES:
        return "season"
    return "projection"


def owner_short(ctx: Context, player: Player) -> str:
    """ME, OPP, the fantasy team's abbreviation, or FA / WA."""
    if player.pool_status != "ONTEAM" or player.on_team_id is None:
        return "WA" if player.pool_status == "WAIVERS" else "FA"
    if player.on_team_id == ctx.snap.my_team_id:
        return "ME"
    if player.on_team_id == ctx.opponent_id(ctx.snap.my_team_id):
        return "OPP"
    team = ctx.snap.team(player.on_team_id)
    return (team.abbrev or team.name) if team else "?"


def rank_players(ctx: Context, key: str) -> tuple[list[dict], list[str]]:
    """(rows best first, the categories valued). Punted categories still get
    a value; they just don't count toward a player's punt value."""
    lines = {
        pid: line
        for pid, player in ctx.snap.players.items()
        if (line := range_line(ctx, player, key)) is not None
    }
    if not lines:
        return [], []
    valuation = Valuation.from_pool(
        [lines[pid] for pid in value_pool(ctx.snap, lines)], ctx.snap.league.categories
    )
    cats = list(valuation.params)
    counted = [c for c in cats if c not in ctx.punt] or cats
    teams = max(ctx.snap.league.size, 1)

    rows = []
    for pid, line in lines.items():
        player = ctx.snap.players[pid]
        values = valuation.by_cat(line)
        league_value = fmean(values.values()) if values else 0.0
        value = fmean(values[c] for c in counted) if counted else 0.0
        rows.append(
            {
                "id": pid,
                "name": player.name,
                "pro_team": player.pro_team,
                "positions": "/".join(positions(player)),
                "owner": ctx.owner_label(player),
                "owner_short": owner_short(ctx, player),
                "injury": INJURY_SHORT.get(player.injury_status, ""),
                "gp": int(line.gp),
                "min": round(line.min, 1),
                "pts": round(line.pts, 1),
                "tpm": round(line.tpm, 1),
                "reb": round(line.reb, 1),
                "ast": round(line.ast, 1),
                "stl": round(line.stl, 1),
                "blk": round(line.blk, 1),
                "to": round(line.to, 1),
                "fga": round(line.fga, 1),
                "fta": round(line.fta, 1),
                "fg_pct": round(line.fgm / line.fga, 3) if line.fga > 0 else None,
                "ft_pct": round(line.ftm / line.fta, 3) if line.fta > 0 else None,
                "usage_proxy": (
                    round(proxy, 1) if (proxy := usage_proxy(line)) is not None else None
                ),
                "values": {c: round(v, 2) for c, v in values.items()},
                "value": round(value, 2),
                "league_value": round(league_value, 2),
            }
        )
    rows.sort(key=lambda r: (-r["value"], r["name"]))
    for i, row in enumerate(rows):
        row["rank"] = i + 1
        row["round"] = i // teams + 1
    return rows, cats
