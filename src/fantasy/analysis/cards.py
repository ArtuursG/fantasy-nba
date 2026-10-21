"""Player cards: everything the dashboard shows when a player is tapped.

One card per player on a roster or in the free-agent pool: recent games,
per-game lines over each period, this matchup's remaining games, and his
value and rank in each rankings period.
"""

from __future__ import annotations

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import game_started, positions
from fantasy.analysis.season import playoff_games, playoff_sps
from fantasy.espn.constants import HEALTH_LABELS
from fantasy.models import Game, Player, StatLine
from fantasy.timeutil import day_label

RECENT_GAMES = 10
SPLITS = ("season", "last30", "last15", "last7", "projected", "prev_season")
GAME_FIELDS = ("min", "pts", "reb", "ast", "tpm", "stl", "blk", "to", "fgm", "fga", "ftm", "fta")


def player_cards(ctx: Context, rankings: dict[str, list[dict]]) -> dict[str, dict]:
    snap = ctx.snap
    ids = {s.player_id for t in snap.teams for s in t.roster} | set(snap.free_agent_ids)
    ranked = {key: {r["id"]: r for r in rows} for key, rows in rankings.items()}
    cards = {}
    po_sps = playoff_sps(ctx)
    for pid in sorted(ids):
        player = snap.players.get(pid)
        if player is not None:
            cards[str(pid)] = _card(ctx, player, ranked, po_sps)
    return cards


def _card(
    ctx: Context, player: Player, ranked: dict[str, dict[int, dict]], po_sps: list[int]
) -> dict:
    remaining = [
        g
        for g in (
            ctx.calendar.team_games(player.pro_team_id, ctx.sps) if player.pro_team_id else []
        )
        if not game_started(g, ctx.now)
    ]
    return {
        "id": player.id,
        "name": player.name,
        "pro_team": player.pro_team,
        "positions": "/".join(positions(player)),
        "owner": ctx.owner_label(player),
        "health": HEALTH_LABELS.get(player.injury_status, player.injury_status),
        "injury_status": player.injury_status,
        "injury_note": player.injury_note,
        "expected_return": player.expected_return,
        "roster_pct": round(player.percent_owned, 1) if player.percent_owned is not None else None,
        "roster_pct_change": (
            round(player.percent_change, 1) if player.percent_change is not None else None
        ),
        "waiver_clear": player.waiver_clear if player.pool_status == "WAIVERS" else None,
        "splits": {key: _line(player.stats[key]) for key in SPLITS if key in player.stats},
        "games": [_game(ctx, g) for g in player.games[-RECENT_GAMES:]][::-1],
        "week": [
            {
                "day": day_label(ctx.calendar.date_of(g.sp)),
                "vs": _vs(ctx, g.home_id, g.away_id, player.pro_team_id),
            }
            for g in remaining
            if ctx.calendar.date_of(g.sp)
        ],
        "playoff_games": playoff_games(ctx, player.pro_team_id, po_sps),
        "values": {
            key: {"value": row["value"], "rank": row["rank"]}
            for key, rows in ranked.items()
            if (row := rows.get(player.id))
        },
    }


def _line(line: StatLine) -> dict | None:
    if line.gp <= 0 and line.min <= 0:
        return None
    out = {name: round(getattr(line, name), 1) for name in ("gp", *GAME_FIELDS)}
    out["fg_pct"] = round(line.fgm / line.fga, 3) if line.fga > 0 else None
    out["ft_pct"] = round(line.ftm / line.fta, 3) if line.fta > 0 else None
    return out


def _game(ctx: Context, game: Game) -> dict:
    day = ctx.calendar.date_of(game.sp)
    pro = next(
        (g for g in ctx.calendar.by_sp.get(game.sp, []) if game.team_id in (g.home_id, g.away_id)),
        None,
    )
    return {
        "day": day_label(day) if day else "",
        "vs": _vs(ctx, pro.home_id, pro.away_id, game.team_id) if pro else "",
        "started": game.started,
        **{name: round(getattr(game.line, name), 1) for name in GAME_FIELDS},
    }


def _vs(ctx: Context, home: int, away: int, team: int) -> str:
    if team == home:
        return ctx.snap.pro_teams.get(away, "?")
    return "@" + ctx.snap.pro_teams.get(home, "?")
