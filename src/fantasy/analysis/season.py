"""Rest of the season: playoff odds and games in the playoff weeks.

Each remaining regular-season matchup on ESPN's schedule is played out
many times. A team's week is its healthy roster's average per-game line
times the games a lineup fills in that many days; each category is won
with the normal approximation used for the current matchup (counting
stats over-dispersed Poisson, percentages binomial). My current matchup
uses its own live forecast. Standings count categories (or matchups, in
a most-categories league); the top teams make the playoffs.
"""

from __future__ import annotations

import math
import random

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import DISPERSION
from fantasy.analysis.schedule import starting_slots
from fantasy.analysis.stats import CAT_FIELDS, PCT_FIELDS, REVERSE_CATS
from fantasy.espn.constants import IR_SLOT, UNAVAILABLE_STATUSES
from fantasy.models import COUNTING_FIELDS
from fantasy.timeutil import parse_iso

SIMS = 1000
GAMES_PER_SLOT_PER_WEEK = 3.3
DEFAULT_PLAYOFF_TEAMS = 4


def playoff_sps(ctx: Context) -> list[int]:
    league = ctx.snap.league
    if not league.regular_periods:
        return []
    return sorted(
        sp
        for period, sps in league.matchup_periods.items()
        if period > league.regular_periods
        for sp in sps
    )


def playoff_games(ctx: Context, pro_team_id: int, sps: list[int]) -> int | None:
    if not sps:
        return None
    if not pro_team_id:
        return 0
    return len(ctx.calendar.team_games(pro_team_id, sps))


def _team_week(ctx: Context, team_id: int) -> dict[str, float]:
    """Per player-game averages of a team's healthy, non-IR players."""
    team = ctx.snap.team(team_id)
    lines = [
        ctx.lines[s.player_id]
        for s in (team.roster if team else [])
        if s.slot_id != IR_SLOT
        and s.player_id in ctx.lines
        and ctx.snap.players[s.player_id].injury_status not in UNAVAILABLE_STATUSES
    ]
    if not lines:
        return dict.fromkeys(COUNTING_FIELDS, 0.0)
    return {name: sum(getattr(x, name) for x in lines) / len(lines) for name in COUNTING_FIELDS}


def _cat_odds(a: dict, b: dict, games: float, cat: str) -> float:
    """Chance team a beats team b in `cat` over a week of `games` starts."""
    if cat in PCT_FIELDS:
        made, att = PCT_FIELDS[cat]
        att_a, att_b = a[att] * games, b[att] * games
        if att_a <= 0 or att_b <= 0:
            return 0.5
        pa, pb = a[made] / a[att], b[made] / b[att]
        sd = math.sqrt(pa * (1 - pa) / att_a + pb * (1 - pb) / att_b)
        diff = pa - pb
    elif cat in CAT_FIELDS:
        field = CAT_FIELDS[cat]
        ma, mb = a[field] * games, b[field] * games
        disp = DISPERSION.get(cat, 1.5)
        sd = math.sqrt((ma + mb) * disp)
        diff = ma - mb
    else:
        return 0.5
    if cat in REVERSE_CATS:
        diff = -diff
    if sd <= 0:
        return 0.5 if diff == 0 else float(diff > 0)
    return 0.5 * (1 + math.erf(diff / sd / math.sqrt(2)))


def season_outlook(ctx: Context, my_odds: dict[str, float] | None) -> dict | None:
    snap = ctx.snap
    league = snap.league
    if not snap.pairings:
        return None
    last = league.regular_periods or max(snap.pairings)
    current = league.matchup_period
    periods = [p for p in sorted(snap.pairings) if current <= p <= last]
    cats = league.categories
    most = (league.scoring_type or "").upper() == "H2H_MOST_CATEGORIES"
    weeks = {t.id: _team_week(ctx, t.id) for t in snap.teams}
    slots = len(starting_slots(league.lineup_slots))

    games_left: list[tuple[int, int, list[float]]] = []
    for period in periods:
        days = len(league.matchup_periods.get(period) or []) or 7
        games = slots * GAMES_PER_SLOT_PER_WEEK * days / 7
        for home, away in snap.pairings[period]:
            if home not in weeks or away not in weeks:
                continue
            mine = snap.my_team_id in (home, away)
            if period == current and mine and my_odds:
                odds = [my_odds.get(c, 0.5) for c in cats]
                if away == snap.my_team_id:
                    odds = [1 - p for p in odds]
            else:
                odds = [_cat_odds(weeks[home], weeks[away], games, c) for c in cats]
            games_left.append((home, away, odds))

    spots = league.playoff_team_count or DEFAULT_PLAYOFF_TEAMS
    teams = [t.id for t in snap.teams]
    base = {t.id: (t.wins, t.losses, t.ties) for t in snap.teams}
    made = dict.fromkeys(teams, 0)
    seeds = dict.fromkeys(teams, 0.0)
    totals = {tid: [0.0, 0.0, 0.0] for tid in teams}
    rng = random.Random(0)
    for _ in range(SIMS):
        record = {tid: list(base[tid]) for tid in teams}
        for home, away, odds in games_left:
            won = sum(1 for p in odds if rng.random() < p)
            lost = len(odds) - won
            if most:
                if won > lost:
                    record[home][0] += 1
                    record[away][1] += 1
                elif lost > won:
                    record[home][1] += 1
                    record[away][0] += 1
                else:
                    record[home][2] += 1
                    record[away][2] += 1
            else:
                record[home][0] += won
                record[home][1] += lost
                record[away][0] += lost
                record[away][1] += won
        order = sorted(teams, key=lambda tid: (-_pct(record[tid]), rng.random()))
        for seed, tid in enumerate(order, 1):
            if seed <= spots:
                made[tid] += 1
            seeds[tid] += seed
            for i in range(3):
                totals[tid][i] += record[tid][i]

    sps = playoff_sps(ctx)
    rows = []
    for t in snap.teams:
        po_games = None
        if sps:
            po_games = sum(
                playoff_games(ctx, snap.players[s.player_id].pro_team_id, sps) or 0
                for s in t.roster
                if s.slot_id != IR_SLOT and s.player_id in snap.players
            )
        rows.append(
            {
                "team_id": t.id,
                "team": t.name,
                "is_me": t.id == snap.my_team_id,
                "record": f"{t.wins}-{t.losses}-{t.ties}",
                "projected": "-".join(f"{totals[t.id][i] / SIMS:.0f}" for i in range(3)),
                "playoff_pct": round(made[t.id] / SIMS, 3),
                "avg_seed": round(seeds[t.id] / SIMS, 1),
                "playoff_games": po_games,
            }
        )
    rows.sort(key=lambda r: (-r["playoff_pct"], r["avg_seed"]))
    return {
        "matchups_left": len(periods),
        "regular_periods": league.regular_periods,
        "playoff_teams": spots,
        "playoff_teams_assumed": league.playoff_team_count is None,
        "playoff_weeks": [p for p in sorted(league.matchup_periods) if p > last],
        "scoring": "matchups" if most else "categories",
        "rows": rows,
    }


def _pct(record: list[float]) -> float:
    played = sum(record)
    return (record[0] + 0.5 * record[2]) / played if played else 0.0


def regular_season_end(ctx: Context) -> int | None:
    league = ctx.snap.league
    if league.regular_periods and league.matchup_periods.get(league.regular_periods):
        return max(league.matchup_periods[league.regular_periods])
    return league.final_scoring_period or None


def rest_of_season_games(ctx: Context) -> tuple[dict[int, int], float]:
    """NBA team id -> regular-season games not yet started, and the median."""
    end = regular_season_end(ctx)
    counts: dict[int, int] = {}
    for team_id, games in ctx.calendar.by_team.items():
        counts[team_id] = sum(
            1 for g in games if (end is None or g.sp <= end) and parse_iso(g.start) > ctx.now
        )
    values = sorted(c for tid, c in counts.items() if tid)
    median = values[len(values) // 2] if values else 0.0
    return counts, float(median)
