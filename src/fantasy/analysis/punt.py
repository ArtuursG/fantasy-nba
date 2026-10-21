"""Which categories this roster could punt.

For each option (no punt, each single category, pairs of my weakest):
my average rank in the categories I'd still play for and my place in
the league by it, and what conceding costs: the categories per week I'd
expect to win in what I punt, against the average team. A good punt costs
little and lifts my place in the rest.
"""

from __future__ import annotations

from itertools import combinations

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import starting_slots
from fantasy.analysis.season import GAMES_PER_SLOT_PER_WEEK, _cat_odds, _team_week

WEAKEST_FOR_PAIRS = 4


def punt_analysis(ctx: Context, strength: dict[int, dict]) -> dict | None:
    snap = ctx.snap
    me = snap.my_team_id
    if me is None or me not in strength:
        return None
    cats = snap.league.categories
    ranks = {tid: s["ranks"] for tid, s in strength.items()}
    games = len(starting_slots(snap.league.lineup_slots)) * GAMES_PER_SLOT_PER_WEEK
    weeks = {t.id: _team_week(ctx, t.id) for t in snap.teams}
    others = [t.id for t in snap.teams if t.id != me]
    odds = {
        cat: sum(_cat_odds(weeks[me], weeks[o], games, cat) for o in others) / len(others)
        for cat in cats
    }
    weakest = sorted(cats, key=lambda c: -ranks[me].get(c, 0))[:WEAKEST_FOR_PAIRS]
    options: list[tuple[str, ...]] = [()] + [(c,) for c in cats]
    options += [tuple(sorted(pair)) for pair in combinations(weakest, 2)]

    rows = []
    for punt in options:
        kept = [c for c in cats if c not in punt]
        avg = {
            tid: sum(r[c] for c in kept if c in r) / max(1, sum(1 for c in kept if c in r))
            for tid, r in ranks.items()
        }
        place = 1 + sum(1 for tid, a in avg.items() if tid != me and a < avg[me])
        rows.append(
            {
                "punt": list(punt),
                "label": " + ".join(punt) if punt else "No punt",
                "avg_rank": round(avg[me], 2),
                "place": place,
                "cost": round(sum(odds[c] for c in punt), 2),
                "expected_cats": round(sum(odds[c] for c in kept), 2),
                "strong": [c for c in kept if ranks[me].get(c, 99) <= 3],
                "weak": [c for c in kept if ranks[me].get(c, 0) >= 8],
                "current": tuple(sorted(ctx.punt)) == tuple(sorted(punt)),
            }
        )
    base = rows[0]
    for row in rows:
        row["place_change"] = base["place"] - row["place"]
    best = min(rows[1:], key=lambda r: (r["place"], r["cost"], r["avg_rank"]), default=None)
    return {"rows": rows, "best": best["label"] if best else None, "my_ranks": ranks[me]}
