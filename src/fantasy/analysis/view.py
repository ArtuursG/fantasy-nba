"""One JSON-ready dict with everything the dashboard and the report show.

`build_view(snapshot, previous, week_ago)` is the only entry point; the
report renderer and the web page both read its output and nothing else.
"""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from fantasy.analysis.actions import build_actions
from fantasy.analysis.advanced import advanced_stats
from fantasy.analysis.cards import player_cards
from fantasy.analysis.changes import compare
from fantasy.analysis.context import Context
from fantasy.analysis.freeagents import rank_free_agents
from fantasy.analysis.lineup import lineup_check
from fantasy.analysis.matchup import (
    SideProjection,
    analyze_matchup,
    day_rows,
    league_game_counts,
    project_side,
    sides_for,
    team_strength,
)
from fantasy.analysis.planner import plan_streams
from fantasy.analysis.rankings import RANGES, default_range, rank_players
from fantasy.analysis.roles import RoleInfo, all_roles, build_alerts, opportunities
from fantasy.analysis.schedule import (
    DayPlan,
    back_to_backs,
    eligible_starting_slots,
    game_started,
    plan_days,
    positions,
)
from fantasy.analysis.simulator import simulate_moves, what_if
from fantasy.analysis.stats import REVERSE_CATS, average, usage_proxy
from fantasy.analysis.strategy import category_strategy, next_matchup
from fantasy.analysis.streaming import Streaming, apply_streaming, expected_streaming
from fantasy.analysis.trade import trade_targets
from fantasy.analysis.weekgrid import add_pickup_ideas, week_grid
from fantasy.espn.constants import (
    BENCH_SLOT,
    C_SLOT,
    HEALTH_LABELS,
    IR_SLOT,
    SLOT_NAMES,
    UNAVAILABLE_STATUSES,
)
from fantasy.models import COUNTING_FIELDS, Player, Snapshot, StatLine, Team
from fantasy.timeutil import day_label, parse_iso

# This league's rules, used where ESPN's settings leave them out.
DEFAULT_ACQUISITION_LIMIT = 5
DEFAULT_WAIVER_DAYS = 1
TOP_FREE_AGENTS = 50
TRANSACTION_DAYS = 7
SOURCE_LABELS = {
    "FREEAGENT": "Free Agency",
    "WAIVER": "Waivers",
    "WAIVER_ERROR": "Waivers",
    "TRADE_ACCEPT": "Trade",
}


def stat_dict(line: StatLine | None) -> dict | None:
    if line is None or (line.gp <= 0 and line.min <= 0 and line.pts <= 0):
        return None
    out = {name: round(getattr(line, name), 2) for name in ("gp", "gs", *COUNTING_FIELDS)}
    out["fg_pct"] = round(line.fgm / line.fga, 3) if line.fga > 0 else None
    out["ft_pct"] = round(line.ftm / line.fta, 3) if line.fta > 0 else None
    return out


def _slot_order(slot_id: int | None) -> tuple[int, int]:
    if slot_id is None:
        return (3, 0)
    if slot_id == IR_SLOT:
        return (2, 0)
    if slot_id == BENCH_SLOT:
        return (1, 0)
    return (0, slot_id)


def player_row(
    ctx: Context,
    player: Player,
    roles: dict[int, RoleInfo],
    slot_id: int | None = None,
    plans: list[DayPlan] | None = None,
) -> dict:
    info = roles[player.id]
    season = player.stats.get("season")
    projected = player.stats.get("projected")
    games = ctx.calendar.team_games(player.pro_team_id, ctx.sps) if player.pro_team_id else []
    remaining = [g for g in games if not game_started(g, ctx.now)]
    last5 = average(info.last5)
    return {
        "id": player.id,
        "name": player.name,
        "pro_team": player.pro_team,
        "positions": "/".join(positions(player)),
        "eligible": ", ".join(
            SLOT_NAMES[s] for s in sorted(eligible_starting_slots(player)) if s in SLOT_NAMES
        ),
        "c_eligible": C_SLOT in player.eligible_slots,
        "slot": SLOT_NAMES.get(slot_id) if slot_id is not None else None,
        "owner": ctx.owner_label(player),
        "health": HEALTH_LABELS.get(player.injury_status, player.injury_status),
        "injury_status": player.injury_status,
        "injury_note": player.injury_note,
        "injury_date": player.injury_date,
        "expected_return": player.expected_return,
        "gp": int(season.gp) if season else 0,
        "season": stat_dict(season),
        "last7": stat_dict(player.stats.get("last7")),
        "last15": stat_dict(player.stats.get("last15")),
        "last30": stat_dict(player.stats.get("last30")),
        "projected": stat_dict(projected),
        "prev_season": stat_dict(player.stats.get("prev_season")),
        "proj_line": stat_dict(ctx.lines[player.id]),
        "projected_min": round(_expected_minutes(info, ctx.lines[player.id]), 1),
        "espn_projected_min": _round(projected.min if projected and projected.min > 0 else None),
        "last5": stat_dict(last5) if info.last5 else None,
        "last5_games": [
            {
                "date": g.date,
                "started": g.started,
                **{name: getattr(g.line, name) for name in COUNTING_FIELDS},
            }
            for g in info.last5
        ],
        "last5_min": info.last5_minutes,
        "last5_starts": info.starts_last5,
        "usage_proxy": _round(usage_proxy(season) if season else None),
        "usage_proxy_last5": _round(usage_proxy(last5) if info.last5 else None),
        "advanced": advanced_stats(ctx, player),
        "roster_pct": _round(player.percent_owned),
        "roster_pct_change": _round(player.percent_change),
        "started_pct": _round(player.percent_started),
        "rater": {
            key: {"rank": r.rank, "rating": _round(r.rating, 2)}
            for key, r in player.ratings.items()
            if r.rank or r.rating
        },
        "draft_rank": player.draft_rank,
        "role": info.role,
        "trend": info.trend,
        "min_delta": _round(info.min_delta),
        "baseline_min": _round(info.baseline_min),
        "baseline_label": info.baseline_label,
        "games_matchup": len(games),
        "games_remaining": len(remaining),
        "usable_remaining": (
            sum(1 for p in plans if player.id in p.started) if plans is not None else None
        ),
        "game_days": [day_label(date.fromisoformat(g.date)) for g in remaining],
        "b2b": back_to_backs([date.fromisoformat(g.date) for g in games]),
        "value": round(ctx.valuation.mean(ctx.lines[player.id], ctx.punt), 2),
        "league_value": round(ctx.valuation.mean(ctx.lines[player.id]), 2),
        "cat_values": {
            cat: round(z, 2) for cat, z in ctx.valuation.by_cat(ctx.lines[player.id]).items()
        },
        "pool_status": player.pool_status,
        "waiver_clear": player.waiver_clear,
        "waiver_clear_estimated": player.waiver_clear_estimated,
    }


def _expected_minutes(info: RoleInfo, line: StatLine) -> float:
    """Minutes to expect next: the recent role once it has clearly changed,
    otherwise the projection line."""
    if info.trend in ("UP", "DOWN") and info.recent_min is not None:
        return info.recent_min
    return line.min


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def team_rows(
    ctx: Context, team: Team, roles: dict[int, RoleInfo], plans: list[DayPlan]
) -> list[dict]:
    spots = sorted(
        team.roster, key=lambda s: (_slot_order(s.slot_id), -ctx.values.get(s.player_id, 0))
    )
    return [
        player_row(ctx, ctx.snap.players[s.player_id], roles, s.slot_id, plans)
        for s in spots
        if s.player_id in ctx.snap.players
    ]


def _transactions(ctx: Context, prev: Snapshot | None) -> list[dict]:
    snap = ctx.snap
    since = ctx.now - timedelta(days=TRANSACTION_DAYS)
    prev_at = parse_iso(prev.fetched_at) if prev else None
    rows = []
    for t in snap.transactions:
        if not t.ts or parse_iso(t.ts) < since:
            continue
        team = snap.team(t.team_id)
        adds = [snap.player_name(i.player_id) for i in t.items if i.type == "ADD"]
        drops = [snap.player_name(i.player_id) for i in t.items if i.type == "DROP"]
        trades = []
        for item in t.items:
            if item.type == "TRADE":
                to_team = snap.team(item.to_team_id)
                trades.append(
                    f"{snap.player_name(item.player_id)} to "
                    f"{to_team.name if to_team else 'team ' + str(item.to_team_id)}"
                )
        if t.type == "WAIVER" and t.status == "EXECUTED":
            result = "claim won"
        elif t.type == "WAIVER_ERROR" or t.status.startswith("FAILED"):
            result = f"claim failed ({t.status})"
        else:
            result = None
        rows.append(
            {
                "ts": t.ts,
                "team": team.name if team else "League",
                "team_id": t.team_id,
                "type": t.type,
                "source": SOURCE_LABELS.get(t.type, t.type),
                "adds": adds,
                "drops": drops,
                "trades": trades,
                "result": result,
                "bid": t.bid,
                "new": prev_at is None or parse_iso(t.ts) > prev_at,
            }
        )
    return rows


def _pickups(ctx: Context, opp_id: int | None, prev: Snapshot | None) -> list[dict]:
    """What every other team added in the last week, with enough about each
    player to judge the move. My opponent comes first. Roster changes since
    the previous snapshot that the transaction log missed are added too."""
    snap = ctx.snap
    since = ctx.now - timedelta(days=TRANSACTION_DAYS)
    by_team: dict[int, dict] = {}
    for team in snap.teams:
        if team.id == snap.my_team_id:
            continue
        by_team[team.id] = {
            "team_id": team.id,
            "team": team.name,
            "is_opp": team.id == opp_id,
            "acquisitions": _acquisitions(ctx, team),
            "adds": [],
            "drops": [],
        }
    for t in snap.transactions:
        if not t.ts or parse_iso(t.ts) < since:
            continue
        if t.type == "WAIVER_ERROR" or t.status.startswith("FAILED"):
            continue
        for item in t.items:
            team_id = item.to_team_id if item.type in ("ADD", "TRADE") else item.from_team_id
            owner = team_id if team_id is not None else t.team_id
            entry = by_team.get(owner) if owner is not None else None
            if entry is None:
                continue
            if item.type in ("ADD", "TRADE"):
                entry["adds"].append(_pickup_row(ctx, item.player_id, t, owner))
            elif item.type == "DROP":
                entry["drops"].append(snap.player_name(item.player_id))
    if prev is not None:
        for team in snap.teams:
            entry = by_team.get(team.id)
            before = prev.team(team.id)
            if entry is None or before is None:
                continue
            had = {s.player_id for s in before.roster}
            listed = {a["id"] for a in entry["adds"]}
            for spot in team.roster:
                if spot.player_id not in had and spot.player_id not in listed:
                    row = _pickup_row(ctx, spot.player_id, None, team.id)
                    row["ts"] = spot.acquisition_date
                    entry["adds"].append(row)
    for entry in by_team.values():
        entry["adds"].sort(key=lambda a: a["ts"] or "", reverse=True)
    rows = [e for e in by_team.values() if e["adds"] or e["drops"]]
    rows.sort(key=lambda e: (not e["is_opp"], -len(e["adds"]), e["team"]))
    return rows


def _pickup_row(ctx: Context, pid: int, t, team_id: int | None) -> dict:
    snap = ctx.snap
    player = snap.players.get(pid)
    team = snap.team(team_id)
    kept = bool(team) and any(s.player_id == pid for s in team.roster)  # type: ignore[union-attr]
    row = {
        "id": pid,
        "name": snap.player_name(pid),
        "ts": t.ts if t else None,
        "source": SOURCE_LABELS.get(t.type, t.type) if t else "Roster change",
        "still_rostered": kept,
        "pro_team": player.pro_team if player else "",
        "positions": "/".join(positions(player)) if player else "",
        "health": player.injury_status if player else "",
        "roster_pct": _round(player.percent_owned) if player else None,
        "recent": None,
        "games_left": None,
        "value": None,
    }
    if player is None:
        return row
    recent = player.stats.get("last15") or player.stats.get("last7") or player.stats.get("season")
    row["recent"] = stat_dict(recent)
    games = ctx.calendar.team_games(player.pro_team_id, ctx.sps) if player.pro_team_id else []
    row["games_left"] = sum(1 for g in games if not game_started(g, ctx.now))
    if pid in ctx.lines:
        row["value"] = round(ctx.valuation.mean(ctx.lines[pid], ctx.punt), 2)
    return row


def _acquisitions(ctx: Context, team: Team) -> dict:
    league = ctx.snap.league
    limit = league.matchup_acquisition_limit or DEFAULT_ACQUISITION_LIMIT
    counted = not team.matchup_acquisitions
    if team.matchup_acquisitions:
        used = team.matchup_acquisitions.get(league.matchup_period, 0)
    else:
        sps = set(ctx.sps)
        used = sum(
            1
            for t in ctx.snap.transactions
            if t.team_id == team.id and t.sp in sps and t.status == "EXECUTED"
            for i in t.items
            if i.type == "ADD"
        )
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "season_total": team.acquisitions_total,
        "counted_from_transactions": counted,
    }


def _ir_status(ctx: Context, team: Team) -> dict:
    players = ctx.snap.players
    in_ir = [s for s in team.roster if s.slot_id == IR_SLOT and s.player_id in players]
    flags = []
    for spot in in_ir:
        player = players[spot.player_id]
        if player.injury_status not in UNAVAILABLE_STATUSES:
            flags.append(
                f"{player.name} is in the IR slot but listed "
                f"{HEALTH_LABELS.get(player.injury_status, player.injury_status)}: ESPN blocks "
                "roster moves until he is activated or moved"
            )
    ir_slots = ctx.snap.league.lineup_slots.get(IR_SLOT, 0)
    if len(in_ir) < ir_slots:
        for spot in team.roster:
            player = players.get(spot.player_id)
            if spot.slot_id != IR_SLOT and player and player.injury_status in UNAVAILABLE_STATUSES:
                flags.append(f"{player.name} is OUT and the IR slot is free: move him to IR")
    return {
        "slots": ir_slots,
        "players": [
            {
                "name": players[s.player_id].name,
                "health": HEALTH_LABELS.get(
                    players[s.player_id].injury_status, players[s.player_id].injury_status
                ),
                "expected_return": players[s.player_id].expected_return,
            }
            for s in in_ir
        ],
        "flags": flags,
    }


def build_view(
    snap: Snapshot,
    prev: Snapshot | None = None,
    week_ago: Snapshot | None = None,
    tz: ZoneInfo | None = None,
    punt: tuple[str, ...] = (),
) -> dict:
    tz = tz or ZoneInfo("Europe/Riga")
    ctx = Context.build(snap, punt)
    roles = all_roles(ctx)
    opps = opportunities(ctx, roles)
    league = snap.league
    me = ctx.my_team
    opp_id = ctx.opponent_id(snap.my_team_id)

    plans: dict[int, list[DayPlan]] = {
        team.id: plan_days(ctx.calendar, snap, team, ctx.values, ctx.sps, ctx.now)
        for team in snap.teams
    }
    strength = team_strength(ctx)

    my_plans = plans.get(me.id, []) if me else []
    my_c = sum(1 for p in (ctx.roster_players(me) if me else []) if C_SLOT in p.eligible_slots)
    fa_ranked = rank_free_agents(ctx, roles, opps, my_plans, my_c)
    top_fa = fa_ranked[:TOP_FREE_AGENTS]

    def fa_row(item: dict) -> dict:
        row = player_row(ctx, snap.players[item["player_id"]], roles)
        row.update(
            {
                "score": item["score"],
                "reasons": item["reasons"],
                "usable_remaining": item["usable"],
                "usable_days": item["usable_days"],
            }
        )
        return row

    matchup = None
    moves = None
    whatif = None
    stream_plan = None
    strategy = None
    candidates = [r["player_id"] for r in fa_ranked if r["games_remaining"] > 0]

    def add_streaming(side: SideProjection) -> Streaming | None:
        """Other teams' expected streaming goes into their projection."""
        if side.team.id == snap.my_team_id:
            return None
        streaming = expected_streaming(
            ctx, side, _acquisitions(ctx, side.team)["remaining"], candidates
        )
        apply_streaming(ctx, side, streaming, candidates)
        return streaming

    if me is not None and opp_id is not None and snap.team(opp_id):
        my_side, opp_side = sides_for(ctx, me.id)
        mine: SideProjection = project_side(ctx, me, my_side)
        theirs = project_side(ctx, snap.team(opp_id), opp_side)  # type: ignore[arg-type]
        opp_streaming = add_streaming(theirs)
        matchup = analyze_matchup(ctx, mine, theirs)
        matchup["opp_streaming"] = opp_streaming.to_dict() if opp_streaming else None
        acquisitions_left = _acquisitions(ctx, me)["remaining"]
        moves = simulate_moves(ctx, mine, theirs, candidates, acquisitions_left)
        whatif = what_if(ctx, mine, theirs, candidates)
        stream_plan = plan_streams(ctx, mine, theirs, candidates, acquisitions_left)
        strategy = category_strategy(ctx, matchup["projected"], candidates)

    teams = []
    for team in snap.teams:
        team_plans = plans[team.id]
        teams.append(
            {
                "id": team.id,
                "name": team.name,
                "abbrev": team.abbrev,
                "owners": team.owners,
                "record": f"{team.wins}-{team.losses}-{team.ties}",
                "waiver_rank": team.waiver_rank,
                "is_me": team.id == snap.my_team_id,
                "is_opp": team.id == opp_id,
                "acquisitions": _acquisitions(ctx, team),
                "games_remaining": sum(len(p.playing) + len(p.unavailable) for p in team_plans),
                "usable_remaining": sum(len(p.started) for p in team_plans),
                "strength": strength[team.id],
                "roster": team_rows(ctx, team, roles, team_plans),
            }
        )

    ranking_rows: dict[str, list[dict]] = {}
    ranking_cats: list[str] = []
    for key, _label in RANGES:
        rows, cats = rank_players(ctx, key)
        ranking_rows[key] = rows
        ranking_cats = ranking_cats or cats
    ranking_range = default_range(ctx)
    rank_by_id = {r["id"]: r["rank"] for r in ranking_rows[ranking_range]}
    recent_value = {r["id"]: r["value"] for r in ranking_rows["last15"]}
    for row in ranking_rows[ranking_range]:
        row["last15_value"] = recent_value.get(row["id"])
    free_agent_rows = [fa_row(item) for item in top_fa]
    streamer_rows = [
        fa_row(item)
        for item in sorted(
            (r for r in fa_ranked if r["usable"] > 0),
            key=lambda r: (r["usable"], r["score"]),
            reverse=True,
        )[:10]
    ]
    for row in [r for t in teams for r in t["roster"]] + free_agent_rows + streamer_rows:
        row["rank"] = rank_by_id.get(row["id"])

    my_ir = _ir_status(ctx, me) if me else None
    prev_at = parse_iso(prev.fetched_at).astimezone(tz) if prev else None
    week_at = parse_iso(week_ago.fetched_at).astimezone(tz) if week_ago else None
    first, last = ctx.calendar.date_of(ctx.sps[0]), ctx.calendar.date_of(ctx.sps[-1])
    days = day_rows(my_plans, plans.get(opp_id) if opp_id else None, ctx)
    changes = compare(ctx, prev)
    alert_ids = [r["player_id"] for r in top_fa]

    grid = week_grid(ctx, me, snap.team(opp_id) if opp_id else None) if me else None
    if grid is not None:
        add_pickup_ideas(ctx, grid, whatif)
    view = {
        "game_counts": league_game_counts(ctx, add_streaming),
        "what_if": whatif,
        "week_grid": grid,
        "meta": {
            "date": ctx.now.astimezone(tz).date().isoformat(),
            "fetched_at": ctx.now.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "fetched_at_iso": ctx.now.isoformat(),
            "timezone": str(tz),
            "league": league.name,
            "league_id": league.id,
            "season": league.season,
            "season_label": f"{league.season - 1}-{str(league.season)[2:]}",
            "teams": league.size,
            "scoring_type": league.scoring_type,
            "categories": league.categories,
            "my_team": me.name if me else None,
            "my_team_id": me.id if me else None,
            "matchup_period": league.matchup_period,
            "matchup_dates": [
                first.isoformat() if first else None,
                last.isoformat() if last else None,
            ],
            "scoring_period": league.scoring_period,
            "compared_with": prev_at.strftime("%Y-%m-%d %H:%M") if prev_at else None,
            "week_ago": week_at.strftime("%Y-%m-%d %H:%M") if week_at else None,
            "demo": snap.demo,
            "warnings": snap.warnings,
            "punt": list(ctx.punt),
            "rules": {
                "lineup": _lineup_text(league.lineup_slots),
                "c_limit": league.c_limit,
                "acquisition_limit": league.matchup_acquisition_limit or DEFAULT_ACQUISITION_LIMIT,
                "waiver_days": (
                    round(league.waiver_hours / 24) if league.waiver_hours else DEFAULT_WAIVER_DAYS
                ),
            },
        },
        "my_team": next((t for t in teams if t["is_me"]), None),
        "my_ir": my_ir,
        "lineup": lineup_check(ctx, me, tz, my_ir["flags"]) if me and my_ir else None,
        "my_c_count": my_c,
        "teams": teams,
        "matchup": matchup,
        "moves": moves,
        "stream_plan": stream_plan,
        "strategy": strategy,
        "next_matchup": next_matchup(ctx, strength),
        "trade_targets": trade_targets(ctx, strength),
        "season_standings": _season_standings(ctx),
        "acquisitions": _acquisitions(ctx, me) if me else None,
        "waiver_order": [
            {"rank": t.waiver_rank, "team": t.name, "is_me": t.id == snap.my_team_id}
            for t in sorted(snap.teams, key=lambda t: t.waiver_rank or 99)
        ],
        "transactions": _transactions(ctx, prev),
        "pickups": _pickups(ctx, opp_id, prev),
        "player_cards": player_cards(ctx, ranking_rows),
        "free_agents": free_agent_rows,
        "popular_free_agents": [
            {
                "name": snap.players[pid].name,
                "pro_team": snap.players[pid].pro_team,
                "positions": "/".join(positions(snap.players[pid])),
                "roster_pct": _round(snap.players[pid].percent_owned),
                "roster_pct_change": _round(snap.players[pid].percent_change),
                "health": HEALTH_LABELS.get(
                    snap.players[pid].injury_status, snap.players[pid].injury_status
                ),
            }
            for pid in sorted(
                snap.free_agent_ids,
                key=lambda pid: snap.players[pid].percent_owned or 0.0,
                reverse=True,
            )[:10]
        ],
        "streamers": streamer_rows,
        "rankings": {
            "default": ranking_range,
            "ranges": [
                {"key": key, "label": label, "players": len(ranking_rows[key])}
                for key, label in RANGES
            ],
            "categories": ranking_cats,
            "rows": ranking_rows,
        },
        "alerts": build_alerts(ctx, roles, opps, prev, alert_ids),
        "schedule": {
            "days": days,
            "low_volume_days": [d["label"] for d in days if d["volume"] == "low"],
            "high_volume_days": [d["label"] for d in days if d["volume"] == "high"],
        },
        "changes": changes,
        "changes_week": compare(ctx, week_ago, ownership_step=10.0),
    }
    view["actions"] = build_actions(view)
    return view


def _season_standings(ctx: Context) -> list[dict] | None:
    """Each team's actual season-to-date category totals from ESPN, ranked."""
    snap = ctx.snap
    teams = [t for t in snap.teams if t.season_stats]
    if not teams:
        return None
    cats = [c for c in snap.league.categories if any(c in t.season_stats for t in teams)]
    ranks: dict[int, dict[str, int]] = {t.id: {} for t in teams}
    for cat in cats:
        scored = {t.id: t.season_stats[cat] for t in teams if cat in t.season_stats}
        for team_id, value in scored.items():
            better = sum(
                1 for v in scored.values() if (v < value if cat in REVERSE_CATS else v > value)
            )
            ranks[team_id][cat] = better + 1
    opp_id = ctx.opponent_id(snap.my_team_id)
    rows = [
        {
            "team": t.name,
            "is_me": t.id == snap.my_team_id,
            "is_opp": t.id == opp_id,
            "record": f"{t.wins}-{t.losses}-{t.ties}",
            "values": {c: t.season_stats.get(c) for c in cats},
            "ranks": ranks[t.id],
            "avg_rank": round(sum(ranks[t.id].values()) / max(len(ranks[t.id]), 1), 1),
        }
        for t in teams
    ]
    return sorted(rows, key=lambda r: r["avg_rank"])


def _lineup_text(slots: dict[int, int]) -> str:
    parts = []
    for slot in sorted(slots, key=lambda s: (s >= BENCH_SLOT, s == 11, s)):
        count = slots[slot]
        name = SLOT_NAMES.get(slot, str(slot))
        parts.append(f"{name} x{count}" if count > 1 else name)
    return ", ".join(parts)
