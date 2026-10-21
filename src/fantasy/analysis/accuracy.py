"""How good the forecasts have been: every recorded category forecast of a
finished matchup scored against what happened.

Brier score is the mean squared gap between the forecast chance and the
outcome (1 win, 0 loss, 0.5 tie): 0 is perfect, 0.25 is a coin flip.
Calibration groups forecasts by how confident they were and shows how
often those calls came true. "First forecast" uses only the first
snapshot of each matchup week, the hardest test.
"""

from __future__ import annotations

from datetime import datetime, tzinfo

OUTCOME = {"WIN": 1.0, "LOSS": 0.0, "TIE": 0.5}
BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def _brier(pairs: list[tuple[float, float]]) -> float | None:
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs) if pairs else None


def forecast_accuracy(
    forecasts: list[tuple[str, int, str, float]], results: dict[tuple[int, str], str]
) -> dict | None:
    scored = [
        (fetched_at, period, cat, p, OUTCOME[results[(period, cat)]])
        for fetched_at, period, cat, p in forecasts
        if (period, cat) in results and results[(period, cat)] in OUTCOME
    ]
    if not scored:
        return None
    categories = [(p, o) for _, _, cat, p, o in scored if cat != "*"]
    matchups = [(p, o) for _, _, cat, p, o in scored if cat == "*"]
    first_seen: dict[int, str] = {}
    for fetched_at, period, *_ in scored:
        first_seen.setdefault(period, fetched_at)
    first = [
        (p, o)
        for fetched_at, period, cat, p, o in scored
        if cat != "*" and fetched_at == first_seen[period]
    ]

    calibration = []
    for low, high in BUCKETS:
        # A 30% forecast is a 70% call on the other side.
        calls = [
            (max(p, 1 - p), o if p >= 0.5 else 1 - o)
            for p, o in categories
            if low <= max(p, 1 - p) < high and o != 0.5
        ]
        if calls:
            calibration.append(
                {
                    "range": f"{low * 100:.0f}-{min(high, 1) * 100:.0f}%",
                    "forecasts": len(calls),
                    "expected": sum(p for p, _ in calls) / len(calls),
                    "actual": sum(o for _, o in calls) / len(calls),
                }
            )
    likely = [(p, o) for p, o in categories if (p >= 0.7 or p <= 0.3) and o != 0.5]
    return {
        "matchups": len({period for _, period, *_ in scored}),
        "forecasts": len(categories),
        "brier": _brier(categories),
        "brier_first": _brier(first),
        "brier_matchup": _brier(matchups),
        "likely_calls": len(likely),
        "likely_correct": (
            sum(1 for p, o in likely if (p >= 0.7) == (o == 1.0)) / len(likely) if likely else None
        ),
        "calibration": calibration,
    }


def win_chance_trend(
    forecasts: list[tuple[str, int, str, float]],
    period: int,
    tz: tzinfo,
    moves: list[dict] | None = None,
) -> dict | None:
    """The matchup win chance at each refresh of this matchup, oldest first,
    with my own roster moves to show what changed it."""
    points: dict[str, dict] = {}
    for fetched_at, item_period, cat, p in forecasts:
        if item_period != period:
            continue
        point = points.setdefault(fetched_at, {"at": fetched_at, "p": None, "expected": 0.0})
        if cat == "*":
            point["p"] = round(p, 3)
        else:
            point["expected"] += p
    rows = [pt for pt in points.values() if pt["p"] is not None]
    if not rows:
        return None
    for pt in rows:
        local = datetime.fromisoformat(pt["at"]).astimezone(tz)
        pt["label"] = local.strftime("%a %H:%M")
        pt["expected"] = round(pt["expected"], 2)
    return {"points": rows, "moves": moves or []}


def first_forecast(forecasts: list[tuple[str, int, str, float]], recap: dict) -> dict | None:
    """The first forecast made for a finished matchup, against how it went."""
    period = recap["period"]
    first_at = min((f[0] for f in forecasts if f[1] == period), default=None)
    if first_at is None:
        return None
    odds = {cat: p for at, item, cat, p in forecasts if at == first_at and item == period}
    results = {c["cat"]: c["result"] for c in recap["categories"]}
    called = [
        cat
        for cat, p in odds.items()
        if cat in results and results[cat] != "TIE" and (p > 0.5) == (results[cat] == "WIN")
    ]
    judged = [cat for cat in odds if cat in results and results[cat] != "TIE"]
    return {
        "at": first_at,
        "p_win_matchup": odds.get("*"),
        "called": len(called),
        "judged": len(judged),
    }
