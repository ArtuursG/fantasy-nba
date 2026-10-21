"""The current head-to-head matchup: score now, projected final, odds.

Remaining output is each day's best lineup (schedule.plan_days) times every
starter's per-game projection. Category odds treat what's left as random:
counting stats as over-dispersed Poisson (variance = mean x dispersion),
percentages as binomial on the attempts still to come. A category is a
likely win or loss once those odds pass 70/30; anything closer is a swing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import DayPlan, plan_days, starting_slots
from fantasy.analysis.stats import CAT_FIELDS, PCT_FIELDS, REVERSE_CATS
from fantasy.espn.constants import IR_SLOT, SLOT_NAMES, UNAVAILABLE_STATUSES
from fantasy.models import COUNTING_FIELDS, MatchupSide, Team
from fantasy.timeutil import day_label

DISPERSION = {"PTS": 2.5, "REB": 1.6, "AST": 1.6, "STL": 1.1, "BLK": 1.3, "3PM": 1.4, "TO": 1.2}
LIKELY = 0.70
PCT_PARTS = {"FG%": ("FGM", "FGA"), "FT%": ("FTM", "FTA")}


@dataclass
class SideProjection:
    team: Team
    side: MatchupSide | None
    remaining_plans: list[DayPlan]
    remaining: dict[str, float] = field(default_factory=dict)
    elapsed: dict[str, float] = field(default_factory=dict)
    played_plans: list[DayPlan] = field(default_factory=list)
    # Games the team is expected to add by streaming (opponents only).
    stream_games: float = 0.0

    @property
    def scheduled_remaining(self) -> int:
        return sum(len(p.playing) + len(p.unavailable) for p in self.remaining_plans)

    @property
    def usable_remaining(self) -> int:
        return sum(len(p.started) for p in self.remaining_plans)

    @property
    def expected_remaining(self) -> float:
        """Usable games left, each weighted by the chance the player plays."""
        return sum(p.chance.get(pid, 1.0) for p in self.remaining_plans for pid in p.started)


def _sum_lines(ctx: Context, plans: list[DayPlan]) -> dict[str, float]:
    totals = dict.fromkeys(COUNTING_FIELDS, 0.0)
    for plan in plans:
        for player_id in plan.started:
            line = ctx.lines[player_id]
            weight = plan.chance.get(player_id, 1.0)
            for name in COUNTING_FIELDS:
                totals[name] += getattr(line, name) * weight
    return totals


def project_side(
    ctx: Context,
    team: Team,
    side: MatchupSide | None,
    elapsed: dict[str, float] | None = None,
    windows: dict[int, tuple[date | None, date | None]] | None = None,
    sps: list[int] | None = None,
) -> SideProjection:
    """Projected rest of a matchup for a roster (the current one unless
    `sps` names another). `elapsed` reuses another projection's estimate of
    what was played so far, so a simulated roster move changes only the
    days ahead; `windows` bounds players' days on the roster."""
    sps = sps or ctx.sps
    remaining = plan_days(ctx.calendar, ctx.snap, team, ctx.values, sps, ctx.now, windows=windows)
    played: list[DayPlan] = []
    if elapsed is None:
        played = plan_days(ctx.calendar, ctx.snap, team, ctx.values, sps, ctx.now, remaining=False)
        # Past games: the player either played or didn't, the box score knows.
        for plan in played:
            plan.chance = {}
        elapsed = _sum_lines(ctx, played)
    return SideProjection(
        team=team,
        side=side,
        remaining_plans=remaining,
        remaining=_sum_lines(ctx, remaining),
        elapsed=elapsed,
        played_plans=played,
    )


def played_games(ctx: Context, side: SideProjection) -> int:
    """Games so far this matchup, estimated: players on the roster as it
    stands now (IR aside) with a box score that day, at most one per starting
    slot. ESPN's matchup data has no games-played count."""
    slots = len(starting_slots(ctx.snap.league.lineup_slots))
    roster = [
        ctx.snap.players[s.player_id]
        for s in side.team.roster
        if s.slot_id != IR_SLOT and s.player_id in ctx.snap.players
    ]
    count = 0
    for plan in side.played_plans:
        played = sum(1 for p in roster if any(g.sp == plan.sp and g.played for g in p.games))
        count += min(played, slots)
    return count


def game_count(ctx: Context, side: SideProjection) -> dict:
    """Games this matchup for one team, and the injured players behind the gap
    between scheduled and expected games."""
    played = played_games(ctx, side)
    expected = side.expected_remaining
    out_games: dict[int, int] = {}
    doubtful: dict[int, list[float]] = {}
    for plan in side.remaining_plans:
        for pid in plan.unavailable:
            out_games[pid] = out_games.get(pid, 0) + 1
        for pid in plan.started:
            if plan.chance.get(pid, 1.0) < 1.0:
                doubtful.setdefault(pid, []).append(plan.chance[pid])
    notes = []
    for pid, games in sorted(out_games.items(), key=lambda kv: -kv[1]):
        player = ctx.snap.players[pid]
        notes.append(
            {"name": player.name, "status": player.injury_status, "games": games, "lost": games}
        )
    for pid, chances in sorted(doubtful.items(), key=lambda kv: -len(kv[1])):
        player = ctx.snap.players[pid]
        notes.append(
            {
                "name": player.name,
                "status": player.injury_status,
                "games": len(chances),
                "lost": round(len(chances) - sum(chances), 1),
            }
        )
    usable = side.usable_remaining
    return {
        "team_id": side.team.id,
        "team": side.team.name,
        "played": played,
        "scheduled_remaining": side.scheduled_remaining,
        "usable_remaining": usable,
        "expected_remaining": round(expected, 1),
        "stream_games": round(side.stream_games, 1),
        "expected_total": round(played + expected + side.stream_games, 1),
        "out_games": sum(out_games.values()),
        "uncertain_games": sum(len(c) for c in doubtful.values()),
        "no_slot_games": side.scheduled_remaining - usable - sum(out_games.values()),
        "injuries": notes,
    }


def league_game_counts(
    ctx: Context, adjust: Callable[[SideProjection], None] | None = None
) -> list[dict]:
    """Game counts for every pairing of the current matchup, mine first.
    `adjust` can change each side's projection first (expected streaming)."""
    rows = []
    seen: set[int] = set()
    for matchup in ctx.snap.matchups:
        if matchup.period != ctx.snap.league.matchup_period or matchup.away is None:
            continue
        pair = []
        for side in (matchup.home, matchup.away):
            team = ctx.snap.team(side.team_id)
            if team is None or team.id in seen:
                continue
            seen.add(team.id)
            projection = project_side(ctx, team, side)
            if adjust is not None:
                adjust(projection)
            pair.append(game_count(ctx, projection))
        if len(pair) == 2:
            pair[0]["opponent"], pair[1]["opponent"] = pair[1]["team"], pair[0]["team"]
            pair[0]["edge"] = round(pair[0]["expected_total"] - pair[1]["expected_total"], 1)
            pair[1]["edge"] = -pair[0]["edge"]
            mine = ctx.snap.my_team_id in (pair[0]["team_id"], pair[1]["team_id"])
            if mine and pair[1]["team_id"] == ctx.snap.my_team_id:
                pair.reverse()
            for row in pair:
                row["is_me"] = row["team_id"] == ctx.snap.my_team_id
            rows = pair + rows if mine else rows + pair
    return rows


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _current(side: SideProjection, name: str) -> float | None:
    return side.side.stats.get(name) if side.side else None


def _final_pct(side: SideProjection, cat: str) -> tuple[float | None, float, bool, float]:
    """(projected final %, its standard deviation, attempts were estimated,
    projected total attempts)."""
    made_field, att_field = PCT_FIELDS[cat]
    made_name, att_name = PCT_PARTS[cat]
    pct_now = _current(side, cat)
    att_now = _current(side, att_name)
    estimated = att_now is None
    if att_now is None:
        att_now = side.elapsed[att_field]
    made_now = _current(side, made_name)
    if made_now is None:
        made_now = pct_now * att_now if pct_now is not None else side.elapsed[made_field]
    made_rem, att_rem = side.remaining[made_field], side.remaining[att_field]
    attempts = att_now + att_rem
    if attempts <= 0:
        return None, 0.0, estimated, 0.0
    rate = made_rem / att_rem if att_rem > 0 else 0.0
    sd = math.sqrt(att_rem * rate * (1 - rate)) / attempts
    return (made_now + made_rem) / attempts, sd, estimated, attempts


def _final_count(side: SideProjection, cat: str) -> tuple[float, float]:
    remaining = side.remaining[CAT_FIELDS[cat]]
    return (_current(side, cat) or 0.0) + remaining, math.sqrt(remaining * DISPERSION[cat])


def win_probability(diff: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
    return _normal_cdf(diff / sd)


# z-score of a 70% chance: the edge a likely win needs, in standard deviations.
LIKELY_Z = 0.5244


def category_outlook(cat: str, mine: SideProjection, theirs: SideProjection) -> dict | None:
    """Projected final for one category and the chance of winning it.

    `edge` is my margin in the category's own units, turned around for TO so
    that positive always means ahead; `sd` is the spread of that margin.
    """
    estimated, attempts = False, 0.0
    if cat in PCT_FIELDS:
        final_me, sd_me, est_me, attempts = _final_pct(mine, cat)
        final_opp, sd_opp, est_opp, _ = _final_pct(theirs, cat)
        estimated = est_me or est_opp
    elif cat in CAT_FIELDS:
        final_me, sd_me = _final_count(mine, cat)
        final_opp, sd_opp = _final_count(theirs, cat)
    else:
        return None
    sd = math.hypot(sd_me, sd_opp)
    if final_me is None or final_opp is None:
        edge, p_win = None, 0.5
    else:
        edge = final_me - final_opp
        if cat in REVERSE_CATS:
            edge = -edge
        p_win = win_probability(edge, sd)
    return {
        "cat": cat,
        "me": final_me,
        "opp": final_opp,
        "edge": edge,
        "sd": sd,
        "p_win": p_win,
        "call": call(p_win),
        "estimated": estimated,
        "my_attempts": attempts,
    }


def record_odds(probabilities: list[float]) -> list[float]:
    """Chance of winning exactly k categories, k = 0..n, treating categories
    as independent (a Poisson-binomial distribution)."""
    odds = [1.0]
    for p in probabilities:
        nxt = [0.0] * (len(odds) + 1)
        for k, q in enumerate(odds):
            nxt[k] += q * (1 - p)
            nxt[k + 1] += q * p
        odds = nxt
    return odds


def matchup_outlook(projected: list[dict]) -> dict:
    """Expected categories won and the chance of winning more categories
    than the opponent."""
    probabilities = [r["p_win"] for r in projected]
    odds = record_odds(probabilities)
    n = len(probabilities)
    return {
        "categories": n,
        "expected_wins": sum(probabilities),
        "p_win_matchup": sum(q for k, q in enumerate(odds) if k > n - k),
        "p_at_least": {k: sum(odds[k:]) for k in range(n + 1)},
    }


def targets(projected: list[dict], mine: SideProjection) -> list[dict]:
    """What it would take in each category short of a likely win: the margin
    needed to draw even and to reach a 70% chance, in the category's units
    (made shots for percentages), and per remaining usable game."""
    games = max(mine.usable_remaining, 1)
    rows = []
    for r in projected:
        if r["edge"] is None or r["p_win"] >= LIKELY:
            continue
        to_even = max(0.0, -r["edge"])
        to_likely = max(0.0, LIKELY_Z * r["sd"] - r["edge"])
        row = {
            "cat": r["cat"],
            "p_win": r["p_win"],
            "edge": r["edge"],
            "to_even": to_even,
            "to_likely": to_likely,
            "per_game": to_likely / games,
            "makes_to_likely": None,
        }
        if r["cat"] in PCT_FIELDS:
            row["makes_to_likely"] = to_likely * r["my_attempts"]
            row["per_game"] = row["makes_to_likely"] / games
        rows.append(row)
    return rows


def call(p_win: float) -> str:
    if p_win >= LIKELY:
        return "Likely win"
    if p_win <= 1 - LIKELY:
        return "Likely loss"
    return "Swing"


def _leader(cat: str, mine: float | None, theirs: float | None) -> str | None:
    if mine is None or theirs is None:
        return None
    if abs(mine - theirs) < 1e-9:
        return "tie"
    ahead = mine > theirs
    if cat in REVERSE_CATS:
        ahead = not ahead
    return "me" if ahead else "opp"


def sides_for(ctx: Context, team_id: int) -> tuple[MatchupSide | None, MatchupSide | None]:
    """(this team's side, the opponent's side) of its current matchup."""
    matchup = ctx.matchup_for(team_id)
    if matchup is None:
        return None, None
    if matchup.home.team_id == team_id:
        return matchup.home, matchup.away
    return matchup.away, matchup.home


def analyze_matchup(ctx: Context, mine: SideProjection, theirs: SideProjection) -> dict:
    my_side = mine.side
    me, opp = mine.team, theirs.team
    current, projected = [], []
    estimated_attempts = False
    for cat in ctx.snap.league.categories:
        now_me, now_opp = _current(mine, cat), _current(theirs, cat)
        current.append(
            {
                "cat": cat,
                "me": now_me,
                "opp": now_opp,
                "leader": _leader(cat, now_me, now_opp),
                "result": my_side.results.get(cat) if my_side else None,
            }
        )
        outlook = category_outlook(cat, mine, theirs)
        if outlook is not None:
            estimated_attempts = estimated_attempts or outlook["estimated"]
            projected.append(outlook)

    first, last = ctx.calendar.date_of(ctx.sps[0]), ctx.calendar.date_of(ctx.sps[-1])
    return {
        "period": ctx.snap.league.matchup_period,
        "dates": [day_label(first) if first else "", day_label(last) if last else ""],
        "me": {"id": me.id, "name": me.name},
        "opp": {"id": opp.id, "name": opp.name},
        "score_now": {
            "wins": my_side.wins if my_side else 0,
            "losses": my_side.losses if my_side else 0,
            "ties": my_side.ties if my_side else 0,
        },
        "current": current,
        "projected": projected,
        "likely_wins": [r["cat"] for r in projected if r["call"] == "Likely win"],
        "likely_losses": [r["cat"] for r in projected if r["call"] == "Likely loss"],
        "swing": [r["cat"] for r in projected if r["call"] == "Swing"],
        "projected_record": _record(projected),
        "games": {"me": game_count(ctx, mine), "opp": game_count(ctx, theirs)},
        "attempts_estimated": estimated_attempts,
        "outlook": matchup_outlook(projected),
        "targets": targets(projected, mine),
    }


def _record(projected: list[dict]) -> str:
    wins = sum(1 for r in projected if r["p_win"] > 0.5)
    losses = sum(1 for r in projected if r["p_win"] < 0.5)
    return f"{wins}-{losses}-{len(projected) - wins - losses}"


def team_strength(ctx: Context, rosters: dict[int, list[int]] | None = None) -> dict[int, dict]:
    """Per-game category output of each roster's healthy, non-IR players,
    ranked 1 (best) to N across the league. `rosters` replaces some teams'
    players (team id -> player ids), to see what a trade would do."""
    values: dict[int, dict[str, float | None]] = {}
    counted: dict[int, int] = {}
    for team in ctx.snap.teams:
        if rosters and team.id in rosters:
            ids = rosters[team.id]
        else:
            ids = [s.player_id for s in team.roster if s.slot_id != IR_SLOT]
        players = [
            ctx.snap.players[pid]
            for pid in ids
            if pid in ctx.snap.players
            and ctx.snap.players[pid].injury_status not in UNAVAILABLE_STATUSES
        ]
        totals = dict.fromkeys(COUNTING_FIELDS, 0.0)
        for player in players:
            for name in COUNTING_FIELDS:
                totals[name] += getattr(ctx.lines[player.id], name)
        cats: dict[str, float | None] = {}
        for cat in ctx.snap.league.categories:
            if cat in PCT_FIELDS:
                made, attempted = PCT_FIELDS[cat]
                cats[cat] = totals[made] / totals[attempted] if totals[attempted] else None
            elif cat in CAT_FIELDS:
                cats[cat] = totals[CAT_FIELDS[cat]]
        values[team.id] = cats
        counted[team.id] = len(players)

    ranks: dict[int, dict[str, int]] = {team_id: {} for team_id in values}
    for cat in ctx.snap.league.categories:
        scored = {tid: v[cat] for tid, v in values.items() if v.get(cat) is not None}
        for team_id, value in scored.items():
            if cat in REVERSE_CATS:
                better = sum(1 for other in scored.values() if other < value)  # type: ignore[operator]
            else:
                better = sum(1 for other in scored.values() if other > value)  # type: ignore[operator]
            ranks[team_id][cat] = better + 1
    return {
        team_id: {"values": values[team_id], "ranks": ranks[team_id], "players": counted[team_id]}
        for team_id in values
    }


def day_rows(plans_me: list[DayPlan], plans_opp: list[DayPlan] | None, ctx: Context) -> list[dict]:
    """Per remaining day: NBA volume, who plays, open slots, for both sides."""
    opp_by_sp = {p.sp: p for p in plans_opp or []}
    rows = []
    for plan in plans_me:
        other = opp_by_sp.get(plan.sp)
        rows.append(
            {
                "sp": plan.sp,
                "date": plan.date.isoformat(),
                "label": day_label(plan.date),
                "nba_games": plan.nba_games,
                "volume": plan.volume,
                "my_playing": [ctx.snap.player_name(p) for p in plan.playing],
                "my_started": len(plan.started),
                "my_benched": [ctx.snap.player_name(p) for p in plan.benched],
                "my_out": [ctx.snap.player_name(p) for p in plan.unavailable],
                "my_open_slots": len(plan.open_slots),
                "my_open_slot_names": _slot_names(plan.open_slots),
                "opp_playing": len(other.playing) if other else 0,
                "opp_started": len(other.started) if other else 0,
                "opp_open_slots": len(other.open_slots) if other else None,
            }
        )
    return rows


def _slot_names(slots: list[int]) -> list[str]:
    return [SLOT_NAMES.get(s, str(s)) for s in slots]
