"""Backtest: the stored snapshots replayed against what happened.

The accuracy log only knows my own matchup, as it was forecast at the time.
Every snapshot holds the whole league, so each one can be forecast again
with the model as it is now, for every pairing of its matchup week, and
scored against the results a later snapshot shows. That is five times the
sample, and a change to the model can be judged on the whole history the
day it is made rather than weeks later.

Three things are measured:

- category and matchup forecasts: Brier score and log loss (lower is
  better; 0.25 and 0.693 are a coin flip), how often the favourite won,
  and calibration;
- the spread: each finished category's actual margin against the projected
  one, in the forecast's own standard deviations. A model that knows how
  unsure it is gets a spread of 1.0; above that it is overconfident;
- player projections: each player's projected per-game line at the start
  of a matchup week against what he then averaged, next to plain season
  and recent averages, so the blend has to earn its keep.

A snapshot only ever sees its own data: nothing from later days leaks into
a forecast.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from statistics import median

from fantasy.analysis.context import Context
from fantasy.analysis.freeagents import rank_free_agents
from fantasy.analysis.habits import apply_lineup_waste, lineup_habits
from fantasy.analysis.matchup import (
    SideProjection,
    category_outlook,
    matchup_outlook,
    project_side,
)
from fantasy.analysis.roles import all_roles, opportunities
from fantasy.analysis.schedule import plan_days
from fantasy.analysis.stats import CAT_FIELDS, REVERSE_CATS, average, cat_value
from fantasy.analysis.streaming import apply_streaming, expected_streaming
from fantasy.analysis.view import _acquisitions
from fantasy.espn.constants import C_SLOT
from fantasy.models import Matchup, Player, Snapshot, StatLine
from fantasy.timeutil import EASTERN

MATCHUP = "*"
EARLY_DAYS = 5
DAY_GROUPS = ["5+ days left", "3-4 days left", "1-2 days left"]
BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
# Forecasts are clipped to this before the log loss, so one certain call
# that went wrong doesn't make the average infinite.
LOG_FLOOR = 0.005
# A player's week counts for the projection test with this many games.
MIN_WEEK_GAMES = 2


@dataclass
class Call:
    """One forecast: the chance the home side wins a category (or, for
    cat '*', the matchup) and what the projection behind it said."""

    fetched_at: str
    period: int
    home: int
    away: int
    cat: str
    p: float
    days_left: int
    edge: float | None = None
    sd: float = 0.0
    # Projected finals of the two sides.
    home_final: float | None = None
    away_final: float | None = None


@dataclass
class Final:
    """How a finished pairing ended, from the home side."""

    results: dict[str, str]
    home: dict[str, float]
    away: dict[str, float]


Adjust = Callable[[Context, SideProjection, list[int], dict[int, dict]], None]


def as_it_stands(
    ctx: Context, side: SideProjection, candidates: list[int], habits: dict[int, dict]
) -> None:
    """The roster as it is, every usable game played."""


def with_habits(
    ctx: Context, side: SideProjection, candidates: list[int], habits: dict[int, dict]
) -> None:
    """What the dashboard does for an opponent: the games the manager usually
    leaves on the bench come off, the streaming he usually does goes on."""
    apply_lineup_waste(side, habits[side.team.id]["waste_rate"])
    streaming = expected_streaming(
        ctx, side, _acquisitions(ctx, side.team)["remaining"], candidates
    )
    apply_streaming(ctx, side, streaming, candidates)


MODELS: dict[str, Adjust] = {"rosters as they stand": as_it_stands, "with habits": with_habits}


def _candidates(ctx: Context) -> list[int]:
    """Free agents in the order the dashboard ranks them (the typical
    streamer is read off the top of this list)."""
    me = ctx.my_team
    roles = all_roles(ctx)
    plans = plan_days(ctx.calendar, ctx.snap, me, ctx.values, ctx.sps, ctx.now) if me else []
    centers = sum(1 for p in (ctx.roster_players(me) if me else []) if C_SLOT in p.eligible_slots)
    ranked = rank_free_agents(ctx, roles, opportunities(ctx, roles), plans, centers)
    return [r["player_id"] for r in ranked if r["games_remaining"] > 0]


def _days_left(ctx: Context) -> int:
    """Days of the matchup not yet over, today included."""
    today = ctx.now.astimezone(EASTERN).date()
    return sum(
        1 for sp in ctx.sps if (day := ctx.calendar.date_of(sp)) is not None and day >= today
    )


def forecast_league(snap: Snapshot, adjust: Adjust = with_habits) -> list[Call]:
    """Every pairing of the snapshot's matchup week, forecast from the home
    side. Punts don't matter here: odds always cover every category."""
    ctx = Context.build(snap)
    period = snap.league.matchup_period
    pairs = [m for m in snap.matchups if m.period == period and m.away is not None]
    if not pairs or not ctx.sps:
        return []
    candidates = _candidates(ctx)
    habits = {t.id: lineup_habits(ctx, t.id) for t in snap.teams}
    days_left = _days_left(ctx)
    calls: list[Call] = []
    for matchup in pairs:
        assert matchup.away is not None
        home, away = snap.team(matchup.home.team_id), snap.team(matchup.away.team_id)
        if home is None or away is None:
            continue
        sides = []
        for team, side in ((home, matchup.home), (away, matchup.away)):
            projection = project_side(ctx, team, side)
            adjust(ctx, projection, candidates, habits)
            sides.append(projection)
        rows = [
            row
            for cat in snap.league.categories
            if (row := category_outlook(cat, sides[0], sides[1])) is not None
        ]
        key = (snap.fetched_at, period, home.id, away.id)
        calls += [
            Call(
                *key,
                row["cat"],
                row["p_win"],
                days_left,
                row["edge"],
                row["sd"],
                row["me"],
                row["opp"],
            )
            for row in rows
        ]
        calls.append(Call(*key, MATCHUP, matchup_outlook(rows)["p_win_matchup"], days_left))
    return calls


def finals(snapshots: Iterable[Snapshot]) -> dict[tuple[int, int, int], Final]:
    """(matchup period, home id, away id) -> how it ended, from every
    finished matchup any snapshot shows."""
    found: dict[tuple[int, int, int], Final] = {}
    for snap in snapshots:
        for matchup in snap.matchups:
            if not _finished(matchup, snap.league.matchup_period):
                continue
            assert matchup.away is not None
            results = dict(matchup.home.results)
            results[MATCHUP] = {"HOME": "WIN", "AWAY": "LOSS"}.get(matchup.winner, "TIE")
            found[(matchup.period, matchup.home.team_id, matchup.away.team_id)] = Final(
                results, matchup.home.stats, matchup.away.stats
            )
    return found


def _finished(matchup: Matchup, current_period: int) -> bool:
    return (
        matchup.away is not None
        and matchup.period < current_period
        and matchup.winner != "UNDECIDED"
        and bool(matchup.home.results)
    )


OUTCOME = {"WIN": 1.0, "LOSS": 0.0, "TIE": 0.5}


def _actual_edge(final: Final, cat: str) -> float | None:
    a, b = final.home.get(cat), final.away.get(cat)
    if a is None or b is None:
        return None
    return b - a if cat in REVERSE_CATS else a - b


def _log_loss(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    total = 0.0
    for p, outcome in pairs:
        p = min(max(p, LOG_FLOOR), 1 - LOG_FLOOR)
        total -= outcome * math.log(p) + (1 - outcome) * math.log(1 - p)
    return total / len(pairs)


def _score(pairs: list[tuple[float, float]]) -> dict:
    """Brier, log loss and how often the favourite won, for (forecast,
    outcome) pairs."""
    decided = [(p, o) for p, o in pairs if o != 0.5 and p != 0.5]
    return {
        "n": len(pairs),
        "brier": sum((p - o) ** 2 for p, o in pairs) / len(pairs) if pairs else None,
        "log_loss": _log_loss(pairs),
        "hit": sum(1 for p, o in decided if (p > 0.5) == (o == 1.0)) / len(decided)
        if decided
        else None,
    }


def _spread(zs: list[float]) -> dict | None:
    """How wide the actual margins fell, in forecast standard deviations.
    `robust` (from the median) ignores a few wild misses; `beyond_2sd`
    should be about 5%."""
    if not zs:
        return None
    return {
        "n": len(zs),
        "bias": sum(zs) / len(zs),
        "rms": math.sqrt(sum(z * z for z in zs) / len(zs)),
        "robust": median(abs(z) for z in zs) / 0.6745,
        "beyond_2sd": sum(1 for z in zs if abs(z) > 2) / len(zs),
    }


def _calibration(pairs: list[tuple[float, float]]) -> list[dict]:
    rows = []
    for low, high in BUCKETS:
        # A 30% forecast is a 70% call on the other side.
        calls = [
            (max(p, 1 - p), o if p >= 0.5 else 1 - o)
            for p, o in pairs
            if low <= max(p, 1 - p) < high and o != 0.5
        ]
        if calls:
            rows.append(
                {
                    "range": f"{low * 100:.0f}-{min(high, 1) * 100:.0f}%",
                    "forecasts": len(calls),
                    "expected": sum(p for p, _ in calls) / len(calls),
                    "actual": sum(o for _, o in calls) / len(calls),
                }
            )
    return rows


def _day_group(days_left: int) -> str:
    if days_left >= EARLY_DAYS:
        return DAY_GROUPS[0]
    return DAY_GROUPS[1] if days_left >= 3 else DAY_GROUPS[2]


def _totals_gap(calls: list[tuple[Call, Final]], cat: str) -> float | None:
    """How far a counting category's actual team totals ended from the ones
    projected early in the week, as a share of the projection: below zero
    means the projections ran high (missed games, mostly)."""
    if cat not in CAT_FIELDS:
        return None
    gaps = []
    for call, final in calls:
        if call.cat != cat or call.days_left < EARLY_DAYS:
            continue
        for projected, actual in (
            (call.home_final, final.home.get(cat)),
            (call.away_final, final.away.get(cat)),
        ):
            if projected and actual is not None:
                gaps.append(actual / projected - 1)
    return sum(gaps) / len(gaps) if gaps else None


def score_calls(calls: list[Call], outcomes: dict[tuple[int, int, int], Final]) -> dict | None:
    """Every forecast of a finished pairing against how it ended."""
    cats: list[tuple[Call, float]] = []
    ended: list[tuple[Call, Final]] = []
    matchups: list[tuple[float, float]] = []
    zs: dict[str, list[float]] = {}
    for call in calls:
        final = outcomes.get((call.period, call.home, call.away))
        if final is None or final.results.get(call.cat) not in OUTCOME:
            continue
        outcome = OUTCOME[final.results[call.cat]]
        if call.cat == MATCHUP:
            matchups.append((call.p, outcome))
            continue
        cats.append((call, outcome))
        ended.append((call, final))
        actual = _actual_edge(final, call.cat)
        if actual is not None and call.edge is not None and call.sd > 0:
            zs.setdefault(call.cat, []).append((actual - call.edge) / call.sd)
    if not cats:
        return None
    pairs = [(c.p, o) for c, o in cats]
    every_z = [z for values in zs.values() for z in values]
    return {
        "pairings": len({(c.period, c.home, c.away) for c, _ in cats}),
        "weeks": len({c.period for c, _ in cats}),
        "days": len({c.fetched_at for c, _ in cats}),
        "categories": _score(pairs),
        "matchups": _score(matchups),
        "spread": _spread(every_z),
        "calibration": _calibration(pairs),
        "by_days_left": [
            {"when": group, **_score(pairs_in)}
            for group in DAY_GROUPS
            if (pairs_in := [(c.p, o) for c, o in cats if _day_group(c.days_left) == group])
        ],
        "by_category": [
            {
                "cat": cat,
                **_score([(c.p, o) for c, o in cats if c.cat == cat]),
                "spread": _spread(zs.get(cat, [])),
                "totals_gap": _totals_gap(ended, cat),
            }
            for cat in dict.fromkeys(c.cat for c, _ in cats)
        ],
    }


# ---- player projections ----------------------------------------------------


def _week_games(player: Player, sps: set[int]) -> StatLine | None:
    games = [g for g in player.games if g.played and g.sp in sps]
    return average(games) if len(games) >= MIN_WEEK_GAMES else None


def _sources(ctx: Context, player: Player) -> dict[str, StatLine]:
    """The lines that could have been used as the projection."""
    lines = {"projection": ctx.lines[player.id]}
    for key in ("season", "last30", "last15", "projected"):
        line = player.stats.get(key)
        if line is not None and line.min > 0 and (key == "projected" or line.gp):
            lines[key] = line
    return lines


SOURCE_LABELS = {
    "projection": "This app's projection",
    "season": "Season average",
    "last30": "Last 30 days",
    "last15": "Last 15 days",
    "projected": "ESPN's projection",
}
IN_SEASON = {"projection", "season", "last30", "last15", "projected"}
VOLUME = {"FG%": ("fgm", "fga", "FGM", "FGA"), "FT%": ("ftm", "fta", "FTM", "FTA")}


def projection_errors(snapshots: list[Snapshot]) -> dict | None:
    """Each rostered player's projected per-game line on the first snapshot
    of a matchup week against his average over that week's games (read from
    the game logs of the latest snapshot that has them).

    The error is the mean absolute gap per game, over the players every
    source has a line for, so the sources are compared on the same players.
    """
    if not snapshots:
        return None
    ordered = sorted(snapshots, key=lambda s: s.fetched_at)
    first_of_week: dict[int, Snapshot] = {}
    for snap in ordered:
        first_of_week.setdefault(snap.league.matchup_period, snap)
    latest = ordered[-1]

    gaps: dict[str, dict[str, list[float]]] = {}
    player_weeks = 0
    weeks = set()
    for period, snap in first_of_week.items():
        if period >= latest.league.matchup_period:
            continue  # not finished: its games aren't all in yet
        ctx = Context.build(snap)
        # Only games still ahead when the snapshot was taken.
        ahead = {sp for sp in ctx.sps if sp > snap.league.scoring_period}
        for team in snap.teams:
            for spot in team.roster:
                player, later = snap.players.get(spot.player_id), latest.players.get(spot.player_id)
                if player is None or later is None:
                    continue
                actual = _week_games(later, ahead)
                sources = _sources(ctx, player)
                # Compare on players every in-season source has a line for.
                if actual is None or not IN_SEASON <= set(sources):
                    continue
                player_weeks += 1
                weeks.add(period)
                for name in sorted(IN_SEASON):
                    line = sources[name]
                    by_cat = gaps.setdefault(name, {})
                    for cat in snap.league.categories:
                        if cat in VOLUME:
                            made, attempted, made_label, att_label = VOLUME[cat]
                            for field, label in ((made, made_label), (attempted, att_label)):
                                by_cat.setdefault(label, []).append(
                                    abs(getattr(line, field) - getattr(actual, field))
                                )
                        elif cat in CAT_FIELDS:
                            mine, real = cat_value(line, cat), cat_value(actual, cat)
                            if mine is not None and real is not None:
                                by_cat.setdefault(cat, []).append(abs(mine - real))
                    by_cat.setdefault("MIN", []).append(abs(line.min - actual.min))
    if not player_weeks:
        return None
    stats = list(next(iter(gaps.values())))
    rows = [
        {
            "source": name,
            "label": SOURCE_LABELS[name],
            "mae": {stat: sum(v) / len(v) for stat, v in by_cat.items()},
        }
        for name, by_cat in gaps.items()
    ]
    # One number per source: each stat's error against the best source's, averaged.
    best = {stat: min(r["mae"][stat] for r in rows) for stat in stats}
    for row in rows:
        row["relative"] = sum(row["mae"][s] / best[s] for s in stats if best[s] > 0) / len(stats)
    rows.sort(key=lambda r: r["relative"])
    return {"player_weeks": player_weeks, "weeks": len(weeks), "stats": stats, "rows": rows}


# ---- the whole run ---------------------------------------------------------


def run_backtest(snapshots: list[Snapshot], models: dict[str, Adjust] | None = None) -> dict | None:
    """Replay every snapshot under each model. None without a finished
    matchup to score against."""
    snapshots = [s for s in snapshots if not s.demo] or snapshots
    outcomes = finals(snapshots)
    if not outcomes:
        return None
    scored = {}
    for name, adjust in (models or MODELS).items():
        calls = [call for snap in snapshots for call in forecast_league(snap, adjust)]
        scored[name] = score_calls(calls, outcomes)
    if not any(scored.values()):
        return None
    return {
        "snapshots": len(snapshots),
        "from": min(s.fetched_at for s in snapshots)[:10],
        "to": max(s.fetched_at for s in snapshots)[:10],
        "models": scored,
        "projections": projection_errors(snapshots),
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def render_backtest(result: dict) -> str:
    lines = [
        f"Backtest: {result['snapshots']} snapshots, {result['from']} to {result['to']}",
        "Brier 0.250 and log loss 0.693 are a coin flip; lower is better.",
        "Spread is the actual margin against the projected one, in forecast standard",
        "deviations: 1.0 is right, above it the forecast is more sure than it should be.",
    ]
    for name, score in result["models"].items():
        lines += ["", f"== {name} =="]
        if score is None:
            lines.append("No finished pairing to score.")
            continue
        cats, mus, spread = score["categories"], score["matchups"], score["spread"]
        lines.append(
            f"{score['pairings']} pairings over {score['weeks']} weeks, "
            f"forecast on {score['days']} days"
        )
        lines.append(
            f"Categories ({cats['n']}): Brier {_num(cats['brier'])}, log loss "
            f"{_num(cats['log_loss'])}, favourite won {_pct(cats['hit'])}"
        )
        lines.append(
            f"Matchups ({mus['n']}): Brier {_num(mus['brier'])}, log loss "
            f"{_num(mus['log_loss'])}, favourite won {_pct(mus['hit'])}"
        )
        if spread:
            lines.append(
                f"Spread: {_num(spread['rms'], 2)} (robust {_num(spread['robust'], 2)}), "
                f"{_pct(spread['beyond_2sd'])} of margins more than 2 sd out (5% expected)"
            )
        lines.append("Calibration (said -> happened):")
        lines += [
            f"  {row['range']:>8}  {_pct(row['expected'])} -> {_pct(row['actual'])}"
            f"  ({row['forecasts']})"
            for row in score["calibration"]
        ]
        lines.append("By time left:")
        lines += [
            f"  {row['when']:<14} Brier {_num(row['brier'])}, favourite won {_pct(row['hit'])}"
            f"  ({row['n']})"
            for row in score["by_days_left"]
        ]
        lines.append("By category:")
        for row in score["by_category"]:
            sp = row["spread"]
            extra = f", spread {_num(sp['robust'], 2)}" if sp else ""
            if row["totals_gap"] is not None:
                extra += f", totals {row['totals_gap'] * 100:+.0f}% against the early projection"
            lines.append(
                f"  {row['cat']:<4} Brier {_num(row['brier'])}, favourite won "
                f"{_pct(row['hit'])}{extra}"
            )
    projections = result.get("projections")
    if projections:
        stats = projections["stats"]
        lines += [
            "",
            f"== Player projections: {projections['player_weeks']} player-weeks over "
            f"{projections['weeks']} weeks ==",
            "Mean gap per game between the line at the start of a week and that week's",
            "average. `rel` is the gap against the best source, averaged over the stats.",
            "  " + f"{'':<22}" + "".join(f"{s:>6}" for s in stats) + f"{'rel':>6}",
        ]
        for row in projections["rows"]:
            lines.append(
                "  "
                + f"{row['label']:<22}"
                + "".join(f"{row['mae'][s]:>6.2f}" for s in stats)
                + f"{row['relative']:>6.2f}"
            )
    return "\n".join(lines) + "\n"


__all__ = [
    "MODELS",
    "Call",
    "Final",
    "finals",
    "forecast_league",
    "projection_errors",
    "render_backtest",
    "run_backtest",
    "score_calls",
]
