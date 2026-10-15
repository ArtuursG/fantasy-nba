"""How good the forecasts have been: every recorded category forecast of a
finished matchup scored against what happened.

Brier score is the mean squared gap between the forecast chance and the
outcome (1 win, 0 loss, 0.5 tie): 0 is perfect, 0.25 is a coin flip.
Calibration groups forecasts by how confident they were and shows how
often those calls came true. "First forecast" uses only the first
snapshot of each matchup week, the hardest test.
"""

from __future__ import annotations

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
