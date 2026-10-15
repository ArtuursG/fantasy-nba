"""Today's lineup check: the slots set in ESPN against the best lineup for
the day's remaining games, so no game is lost to a starter without a game,
an injured starter or a forgotten IR move."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import (
    eligible_starting_slots,
    game_started,
    is_available,
    plan_days,
)
from fantasy.espn.constants import (
    HEALTH_LABELS,
    IR_SLOT,
    NON_STARTING_SLOTS,
    SLOT_NAMES,
    UNAVAILABLE_STATUSES,
)
from fantasy.models import ProGame, Team
from fantasy.timeutil import day_label, parse_iso

WATCH_STATUSES = {"DAY_TO_DAY", "QUESTIONABLE", "DOUBTFUL"}


def _next_day_with_games(ctx: Context) -> int | None:
    """The current scoring period if games are still to tip off, else the
    next one that has games."""
    for sp in sorted(s for s in ctx.calendar.by_sp if s >= ctx.snap.league.scoring_period):
        if any(not game_started(g, ctx.now) for g in ctx.calendar.by_sp[sp]):
            return sp
    return None


def _pair_swaps(
    start_in: list[dict], bench_out: list[dict], team: Team, players: dict
) -> list[dict]:
    """Pair each player to start with a starter who can't play today and
    holds a slot he fits, preferring idle starters over injured ones."""
    by_name = {players[s.player_id].name: s for s in team.roster if s.player_id in players}
    free = sorted(bench_out, key=lambda b: b["reason"] != "no game")
    swaps = []
    for item in start_in:
        spot = by_name.get(item["name"])
        eligible = eligible_starting_slots(players[spot.player_id]) if spot else set()
        partner = next(
            (b for b in free if by_name.get(b["name"]) and by_name[b["name"]].slot_id in eligible),
            None,
        )
        if partner:
            free.remove(partner)
        swaps.append(
            {
                "start": item["name"],
                "for": partner["name"] if partner else None,
                "reason": partner["reason"] if partner else None,
                "slot": SLOT_NAMES.get(by_name[partner["name"]].slot_id) if partner else None,
                "tipoff": item["tipoff"],
            }
        )
    return swaps


def lineup_check(ctx: Context, team: Team, tz: ZoneInfo, ir_flags: list[str]) -> dict | None:
    sp = _next_day_with_games(ctx)
    if sp is None:
        return None
    (plan,) = plan_days(ctx.calendar, ctx.snap, team, ctx.values, [sp], ctx.now) or [None]
    if plan is None:
        return None
    players = ctx.snap.players
    games: dict[int, ProGame] = {}
    for game in ctx.calendar.by_sp.get(sp, []):
        if not game_started(game, ctx.now):
            games[game.home_id] = game
            games[game.away_id] = game

    def tipoff(team_id: int) -> str:
        game = games.get(team_id)
        return parse_iso(game.start).astimezone(tz).strftime("%H:%M") if game else ""

    starting = {s.player_id for s in team.roster if s.slot_id not in NON_STARTING_SLOTS}
    best = set(plan.started)
    current_starts = 0
    bench_out, start_in, consider, watch = [], [], [], []
    for spot in team.roster:
        player = players.get(spot.player_id)
        if player is None or spot.slot_id == IR_SLOT:
            continue
        has_game = player.pro_team_id in games
        available = is_available(player, plan.date)
        if spot.player_id in starting:
            if has_game and available:
                current_starts += 1
                if spot.player_id not in best:
                    consider.append(f"{player.name} plays but the best lineup sits him")
            elif has_game:
                label = HEALTH_LABELS.get(player.injury_status, player.injury_status)
                bench_out.append({"name": player.name, "reason": label})
            else:
                bench_out.append({"name": player.name, "reason": "no game"})
        elif spot.player_id in best:
            start_in.append(
                {"name": player.name, "team": player.pro_team, "tipoff": tipoff(player.pro_team_id)}
            )
        if spot.player_id in best and player.injury_status in WATCH_STATUSES:
            watch.append(
                f"{player.name} ({HEALTH_LABELS.get(player.injury_status, player.injury_status)})"
            )

    swaps = _pair_swaps(start_in, bench_out, team, players)

    starters_with_games = [players[pid] for pid in best if players[pid].pro_team_id in games]
    first_tip = min(
        (parse_iso(games[p.pro_team_id].start) for p in starters_with_games), default=None
    )
    # A bench_out entry only costs a game when someone could take the slot.
    lost = max(0, len(best) - current_starts)
    return {
        "sp": sp,
        "day": day_label(plan.date),
        "is_today": sp == ctx.snap.league.scoring_period,
        "lock": first_tip.astimezone(tz).strftime("%Y-%m-%d %H:%M") if first_tip else None,
        "current_starts": current_starts,
        "best_starts": len(best),
        "lost_games": lost,
        "start": start_in,
        "swaps": swaps,
        "bench": [b for b in bench_out if b["reason"] != "no game"],
        "consider": consider,
        "watch": watch,
        "ir": ir_flags,
        "open_slots": len(plan.open_slots),
        "ok": lost == 0
        and not watch
        and not ir_flags
        and not any(b["reason"] != "no game" for b in bench_out),
        "out_starters": [b["name"] for b in bench_out if b["reason"] != "no game"],
        "unavailable": [players[p].name for p in plan.unavailable],
        "injured_on_roster": [
            players[s.player_id].name
            for s in team.roster
            if s.player_id in players
            and players[s.player_id].injury_status in UNAVAILABLE_STATUSES
            and s.slot_id != IR_SLOT
        ],
    }
