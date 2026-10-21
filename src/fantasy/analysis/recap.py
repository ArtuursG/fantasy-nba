"""The matchup that just finished: how it was won or lost.

Final category totals and margins (which were close), games played and
games left on the bench by each side, acquisitions left unused, and
what a streamer would have needed to flip the close losses.
"""

from __future__ import annotations

from fantasy.analysis.context import Context
from fantasy.analysis.habits import lineup_habits
from fantasy.analysis.stats import REVERSE_CATS
from fantasy.timeutil import day_label

DEFAULT_ACQUISITION_LIMIT = 5
CLOSE_SHARE = 0.06  # counting categories within 6%
CLOSE_PCT = 0.012  # percentages within 1.2 points


def last_matchup_recap(ctx: Context) -> dict | None:
    snap = ctx.snap
    me = snap.my_team_id
    period = snap.league.matchup_period - 1
    if me is None or period < 1:
        return None
    matchup = ctx.matchup_for(me, period)
    if matchup is None or matchup.away is None:
        return None
    mine, theirs = (
        (matchup.home, matchup.away) if matchup.home.team_id == me else (matchup.away, matchup.home)
    )
    if not mine.stats:
        return None
    opp = snap.team(theirs.team_id)
    cats = []
    for cat in snap.league.categories:
        a, b = mine.stats.get(cat), theirs.stats.get(cat)
        if a is None or b is None:
            continue
        diff = a - b if cat not in REVERSE_CATS else b - a
        if cat.endswith("%"):
            close = abs(diff) <= CLOSE_PCT
        else:
            close = abs(diff) <= CLOSE_SHARE * max(abs(a), abs(b), 1.0)
        result = mine.results.get(cat) or ("WIN" if diff > 0 else "LOSS" if diff < 0 else "TIE")
        cats.append(
            {"cat": cat, "me": a, "opp": b, "margin": diff, "result": result, "close": close}
        )
    sps = snap.league.matchup_periods.get(period) or []
    first, last = (
        ctx.calendar.date_of(sps[0]) if sps else None,
        (ctx.calendar.date_of(sps[-1]) if sps else None),
    )

    def games(team_id: int) -> int | None:
        days = [snap.daily_totals.get(sp, {}).get(team_id) for sp in sps]
        return int(sum(d["GP"] for d in days if d)) if any(days) else None

    my_team = snap.team(me)
    limit = snap.league.matchup_acquisition_limit or DEFAULT_ACQUISITION_LIMIT
    used = my_team.matchup_acquisitions.get(period) if my_team else None
    my_habits = lineup_habits(ctx, me, sps)
    opp_habits = lineup_habits(ctx, theirs.team_id, sps)
    close_losses = [c["cat"] for c in cats if c["close"] and c["result"] == "LOSS"]
    close_wins = [c["cat"] for c in cats if c["close"] and c["result"] == "WIN"]
    notes = []
    if close_losses:
        notes.append(f"Close losses: {', '.join(close_losses)}.")
    if used is not None and used < limit and close_losses:
        notes.append(
            f"{limit - used} acquisition(s) went unused; a streamer or two might have flipped "
            f"{'it' if len(close_losses) == 1 else 'some of them'}."
        )
    if my_habits["days"] and my_habits["lost_games"]:
        notes.append(f"{my_habits['lost_games']} game(s) were left on your bench.")
    if close_wins:
        notes.append(f"Held on in {', '.join(close_wins)}.")
    return {
        "period": period,
        "dates": [day_label(first) if first else "", day_label(last) if last else ""],
        "opponent": opp.name if opp else "Opponent",
        "score": {"wins": mine.wins, "losses": mine.losses, "ties": mine.ties},
        "result": "WIN"
        if mine.wins > mine.losses
        else "LOSS"
        if mine.losses > mine.wins
        else "TIE",
        "categories": cats,
        "games": {"me": games(me), "opp": games(theirs.team_id)},
        "bench_games": {
            "me": my_habits["lost_games"] if my_habits["days"] else None,
            "opp": opp_habits["lost_games"] if opp_habits["days"] else None,
        },
        "acquisitions": {"used": used, "limit": limit},
        "notes": notes,
    }
