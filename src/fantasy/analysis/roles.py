"""Role and injury changes: minutes trends, new starters, returns from
injury, teammates' injuries and add-rate surges, from game logs, the NBA
schedule and the previous snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import fmean

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import is_available, positions
from fantasy.analysis.stats import average, played_games
from fantasy.espn.constants import HEALTH_LABELS, UNAVAILABLE_STATUSES
from fantasy.models import Game, Player, Snapshot
from fantasy.timeutil import parse_iso

MIN_TREND = 4.0
TREND_GAMES = 3
PRIOR_WINDOW = 10
RETURN_MISSED = 3
RETURN_BACK_MAX = 3
OPPORTUNITY_MIN = 24.0
ROOM_MIN = 30.0
ADD_SURGE = 5.0
# Box scores reach ESPN some hours after tip-off; a game this recent with no
# stats line is not yet a missed game.
STATS_LAG = timedelta(hours=4)


@dataclass
class RoleInfo:
    last5: list[Game]
    recent_min: float | None
    baseline_min: float | None
    baseline_label: str
    min_delta: float | None
    trend: str
    starts_last5: int
    start_rate_before: float | None
    new_starter: bool
    lost_start: bool
    missed_now: int
    returned: tuple[int, int] | None
    no_prev_season: bool

    @property
    def role(self) -> str:
        if not self.last5:
            return "No recent games"
        kind = "Starter" if self.starts_last5 >= 3 else "Bench"
        return f"{kind}, ~{self.recent_min:.0f} MIN"

    @property
    def last5_minutes(self) -> list[float]:
        return [g.line.min for g in self.last5]


def _team_history(player: Player, ctx: Context, log_start: int | None) -> list[int]:
    """Scoring periods of the player's current NBA team's finished games
    inside the game-log window, after any trade."""
    if not player.pro_team_id or log_start is None:
        return []
    traded_after = max(
        (g.sp for g in player.games if g.team_id and g.team_id != player.pro_team_id),
        default=log_start - 1,
    )
    cutoff = ctx.now - STATS_LAG
    return [
        g.sp
        for g in ctx.calendar.by_team.get(player.pro_team_id, [])
        if g.sp >= log_start and g.sp > traded_after and parse_iso(g.start) <= cutoff
    ]


def role_info(player: Player, ctx: Context, log_start: int | None) -> RoleInfo:
    played = played_games(player)
    last5 = played[-5:]
    prior = played[-5 - PRIOR_WINDOW : -5] if len(played) > 5 else []
    recent_min = fmean(g.line.min for g in last5) if last5 else None

    season = player.stats.get("season")
    prev = player.stats.get("prev_season")
    projected = player.stats.get("projected")
    if len(prior) >= TREND_GAMES:
        baseline, label = fmean(g.line.min for g in prior), f"previous {len(prior)} games"
    elif season and season.gp >= TREND_GAMES:
        baseline, label = season.min, "season average"
    elif prev and prev.gp >= TREND_GAMES:
        baseline, label = prev.min, "last season"
    elif projected and projected.min > 0:
        baseline, label = projected.min, "ESPN projection"
    else:
        baseline, label = None, ""

    delta = None
    trend = "-"
    if recent_min is not None and baseline is not None and len(last5) >= TREND_GAMES:
        delta = recent_min - baseline
        trend = "UP" if delta >= MIN_TREND else "DOWN" if delta <= -MIN_TREND else "STEADY"

    starts = sum(1 for g in last5 if g.started)
    if len(prior) >= TREND_GAMES:
        rate_before: float | None = sum(1 for g in prior if g.started) / len(prior)
    elif season and season.gp >= 5:
        rate_before = season.gs / season.gp
    else:
        rate_before = None

    history = _team_history(player, ctx, log_start)
    played_sps = {g.sp for g in played}
    flags = [sp in played_sps for sp in history]
    missed_now = 0
    for flag in reversed(flags):
        if flag:
            break
        missed_now += 1
    back = 0
    for flag in reversed(flags):
        if not flag:
            break
        back += 1
    missed_before = 0
    for flag in reversed(flags[: len(flags) - back]):
        if flag:
            break
        missed_before += 1
    returned = (
        (missed_before, back)
        if 1 <= back <= RETURN_BACK_MAX and missed_before >= RETURN_MISSED
        else None
    )
    if missed_now >= RETURN_MISSED:
        # Not playing right now: a trend from his last games would be stale.
        delta, trend = None, "-"

    return RoleInfo(
        last5=last5,
        recent_min=recent_min,
        baseline_min=baseline,
        baseline_label=label,
        min_delta=delta,
        trend=trend,
        starts_last5=starts,
        start_rate_before=rate_before,
        new_starter=(
            len(last5) >= TREND_GAMES
            and starts >= 3
            and rate_before is not None
            and rate_before <= 0.25
        ),
        lost_start=len(last5) >= TREND_GAMES
        and starts <= 1
        and rate_before is not None
        and rate_before >= 0.75,
        missed_now=missed_now,
        returned=returned,
        no_prev_season=bool(played) and (prev is None or prev.gp == 0),
    )


def log_start_sp(snap: Snapshot) -> int | None:
    """First scoring period the game logs cover, from the earliest game seen."""
    return min((g.sp for p in snap.players.values() for g in p.games), default=None)


def all_roles(ctx: Context) -> dict[int, RoleInfo]:
    start = log_start_sp(ctx.snap)
    return {pid: role_info(p, ctx, start) for pid, p in ctx.snap.players.items()}


def opportunities(ctx: Context, roles: dict[int, RoleInfo]) -> dict[int, list[dict]]:
    """Healthy teammates who share a position with an injured rotation
    player. The minutes estimate splits the injured player's minutes among
    them (plus one for the rest of the bench), capped at 10. Each also says
    how long the chance lasts (the injured player's expected return and the
    team games until then) and what the teammate did with him and without
    him in the games logged; with no games beside him, ESPN's projection
    stands for the normal role."""
    today = ctx.now.date()
    by_team: dict[int, list[Player]] = {}
    for player in ctx.snap.players.values():
        if player.pro_team_id:
            by_team.setdefault(player.pro_team_id, []).append(player)

    found: dict[int, list[dict]] = {}
    for injured in ctx.snap.players.values():
        if injured.injury_status not in UNAVAILABLE_STATUSES or not injured.pro_team_id:
            continue
        minutes = ctx.lines[injured.id].min
        if minutes < OPPORTUNITY_MIN:
            continue
        spots = set(positions(injured))
        mates = [
            p
            for p in by_team.get(injured.pro_team_id, [])
            if p.id != injured.id
            and is_available(p, today)
            and spots & set(positions(p))
            and ctx.lines[p.id].min < ROOM_MIN
        ]
        rotation = [p for p in mates if ctx.lines[p.id].min >= 10] or mates
        if not rotation:
            continue
        bump = min(10.0, minutes / (len(rotation) + 1))
        played_with = {g.sp for g in played_games(injured)}
        games_away = _games_until(ctx, injured.pro_team_id, injured.expected_return)
        for mate in rotation:
            item = {
                "player": injured.name,
                "status": HEALTH_LABELS.get(injured.injury_status, injured.injury_status),
                "minutes": minutes,
                "missed": roles[injured.id].missed_now,
                "bump": bump,
                "expected_return": injured.expected_return,
                "games_away": games_away,
            }
            item.update(_with_and_without(ctx, mate, played_with))
            found.setdefault(mate.id, []).append(item)
    return found


def _games_until(ctx: Context, team_id: int, expected_return: str | None) -> int | None:
    """The team's games from now until the expected return (None: unknown)."""
    if not expected_return:
        return None
    back = date.fromisoformat(expected_return)
    return sum(
        1
        for g in ctx.calendar.by_team.get(team_id, [])
        if parse_iso(g.start) > ctx.now and parse_iso(g.start).date() < back
    )


def _with_and_without(ctx: Context, mate: Player, played_with: set[int]) -> dict:
    games = played_games(mate)
    beside = [g for g in games if g.sp in played_with]
    alone = [g for g in games if g.sp not in played_with]
    out: dict = {"without_games": len(alone), "with_games": len(beside)}
    if alone:
        line = average(alone)
        out["without_min"] = round(line.min, 1)
        out["without_value"] = round(ctx.valuation.mean(line, ctx.punt), 2)
    if beside:
        line = average(beside)
        out["with_min"] = round(line.min, 1)
        out["with_value"] = round(ctx.valuation.mean(line, ctx.punt), 2)
        out["with_basis"] = "with him"
    else:
        projected = mate.stats.get("projected")
        if projected is not None and projected.min > 0:
            out["with_min"] = round(projected.min, 1)
            out["with_value"] = round(ctx.valuation.mean(projected, ctx.punt), 2)
            out["with_basis"] = "ESPN projection"
    return out


def opportunity_text(item: dict) -> str:
    """One line on a fill-in chance: whose minutes, for how long, and the
    role with and without him."""
    back = item.get("expected_return")
    away = item.get("games_away")
    if back:
        window = f"back ~{back[5:]}" + (f", {away} team games away" if away is not None else "")
    else:
        window = "return date unknown"
    text = f"Fill-in for {item['player']} ({item['status']}, {window})"
    if item.get("without_games") and item.get("with_min") is not None:
        text += (
            f": {item['without_min']:.0f} MIN without him vs {item['with_min']:.0f} "
            f"{'with him' if item.get('with_basis') == 'with him' else 'projected'}"
        )
        if item.get("without_value") is not None and item.get("with_value") is not None:
            text += f" (value {item['without_value']:+.2f} vs {item['with_value']:+.2f})"
        gain = item["without_min"] - item["with_min"]
        if gain >= 3:
            text += "; the role shrinks when he returns"
        elif gain <= -3:
            text += "; no bigger role without him so far"
    else:
        text += f": about +{item['bump']:.0f} MIN while he is out"
    return text


def _fmt_minutes(values: list[float]) -> str:
    return ", ".join(f"{m:.0f}" for m in values)


def player_alert(
    player: Player,
    info: RoleInfo,
    owner: str,
    prev_player: Player | None,
    opportunity: list[dict],
) -> dict | None:
    lines: list[str] = []
    kinds: list[str] = []
    out = player.injury_status in UNAVAILABLE_STATUSES

    if prev_player is not None and prev_player.injury_status != player.injury_status:
        before = HEALTH_LABELS.get(prev_player.injury_status, prev_player.injury_status)
        now = HEALTH_LABELS.get(player.injury_status, player.injury_status)
        lines.append(f"Injury status changed: {before} -> {now}")
        kinds.append("injury_change")
    if out:
        detail = f"Out: missed last {info.missed_now} team games" if info.missed_now else "Out"
        if player.expected_return:
            detail += f"; expected return {player.expected_return}"
        lines.append(detail)
        kinds.append("out")
    if player.injury_note and (out or "injury_change" in kinds or player.injury_status != "ACTIVE"):
        lines.append(f"Note: {player.injury_note}")

    if info.returned:
        missed, back = info.returned
        since = [g.line.min for g in info.last5[-back:]]
        ramp = (
            "ramping up"
            if info.baseline_min is not None and fmean(since) < info.baseline_min - MIN_TREND
            else "full workload"
        )
        lines.append(f"Returned after missing {missed} games; back for {back}")
        baseline = f" (previous average {info.baseline_min:.0f} MIN)" if info.baseline_min else ""
        lines.append(f"Minutes since return: {_fmt_minutes(since)}{baseline}")
        lines.append(f"Status: {ramp}")
        kinds.append("returned")
    elif not out and info.missed_now >= 3 and player.injury_status == "ACTIVE":
        lines.append(f"No minutes in the last {info.missed_now} team games (out of rotation?)")
        kinds.append("dnp")

    if info.trend in ("UP", "DOWN") and not info.returned:
        was = "starter" if (info.start_rate_before or 0) >= 0.5 else "bench"
        lines.append(f"Previous role: {was}, ~{info.baseline_min:.0f} MIN ({info.baseline_label})")
        lines.append(
            f"Current role: {info.recent_min:.0f} MIN last {len(info.last5)} "
            f"({_fmt_minutes(info.last5_minutes)}), started {info.starts_last5}"
        )
        lines.append(f"Trend: {info.trend} ({info.min_delta:+.1f} MIN)")
        kinds.append("minutes_up" if info.trend == "UP" else "minutes_down")
    if info.new_starter:
        lines.append(
            f"Promoted to starter: started {info.starts_last5} of last {len(info.last5)} "
            f"(before: {info.start_rate_before:.0%} of games)"
        )
        kinds.append("new_starter")
    if info.lost_start:
        lines.append(
            f"Lost starting role: started {info.starts_last5} of last {len(info.last5)} "
            f"(before: {info.start_rate_before:.0%})"
        )
        kinds.append("lost_start")

    for item in opportunity:
        lines.append(opportunity_text(item))
        kinds.append("teammate_out")

    if owner in ("FA", "WA") and (player.percent_change or 0) >= ADD_SURGE:
        lines.append(
            f"Add trend: +{player.percent_change:.1f}% "
            f"(rostered {player.percent_owned or 0:.1f}% of ESPN leagues)"
        )
        kinds.append("add_trend")
    if info.no_prev_season and ("minutes_up" in kinds or "new_starter" in kinds):
        lines.append("No NBA stats last season (likely a rookie) and the role is growing")
        kinds.append("rookie_rising")

    if not kinds:
        return None
    if "out" in kinds or "injury_change" in kinds:
        trend = "INJURY"
    elif any(k in kinds for k in ("minutes_up", "new_starter", "teammate_out", "returned")):
        trend = "UP"
    elif any(k in kinds for k in ("minutes_down", "lost_start", "dnp")):
        trend = "DOWN"
    else:
        trend = "WATCH"
    return {
        "player_id": player.id,
        "name": player.name,
        "pro_team": player.pro_team,
        "owner": owner,
        "trend": trend,
        "kinds": kinds,
        "lines": lines,
    }


OWNER_ORDER = {"MY TEAM": 0, "FA": 1, "WA": 1}
# Alerts for players on other fantasy teams that are worth showing; their
# minutes changes only when large.
OTHER_TEAM_KINDS = {"injury_change", "returned", "new_starter", "lost_start"}
OTHER_TEAM_MIN_TREND = 6.0


def build_alerts(
    ctx: Context,
    roles: dict[int, RoleInfo],
    opps: dict[int, list[dict]],
    prev: Snapshot | None,
    free_agent_ids: list[int],
) -> list[dict]:
    """Alerts for my roster, the opponent's, the listed free agents, and
    the sharpest changes on other teams."""
    candidates = {s.player_id for t in ctx.snap.teams for s in t.roster} | set(free_agent_ids)
    alerts = []
    for player_id in candidates:
        player = ctx.snap.players.get(player_id)
        if player is None:
            continue
        owner = ctx.owner_label(player)
        prev_player = prev.players.get(player_id) if prev else None
        alert = player_alert(player, roles[player_id], owner, prev_player, opps.get(player_id, []))
        if alert is None:
            continue
        mine_or_opp = owner == "MY TEAM" or owner.startswith("OPPONENT")
        if owner not in ("FA", "WA") and not mine_or_opp:
            delta = abs(roles[player_id].min_delta or 0.0)
            if not set(alert["kinds"]) & OTHER_TEAM_KINDS and delta < OTHER_TEAM_MIN_TREND:
                continue
        alerts.append(alert)

    def order(alert: dict) -> tuple[int, int, float]:
        owner = alert["owner"]
        rank = OWNER_ORDER.get(owner, 2 if owner.startswith("OPPONENT") else 3)
        return rank, 0 if alert["trend"] == "INJURY" else 1, -ctx.values.get(alert["player_id"], 0)

    return sorted(alerts, key=order)
