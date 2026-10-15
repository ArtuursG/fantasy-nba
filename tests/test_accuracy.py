import pytest

from fantasy.analysis.accuracy import forecast_accuracy
from fantasy.store import SnapshotStore


def test_brier_score_and_calibration():
    forecasts = [
        ("t1", 4, "PTS", 0.9),
        ("t1", 4, "REB", 0.2),
        ("t1", 4, "*", 0.8),
        ("t2", 4, "PTS", 0.95),
        ("t2", 4, "REB", 0.1),
        ("t2", 5, "PTS", 0.6),  # matchup 5 isn't finished: ignored
    ]
    results = {(4, "PTS"): "WIN", (4, "REB"): "WIN", (4, "*"): "WIN"}
    acc = forecast_accuracy(forecasts, results)
    assert acc["matchups"] == 1 and acc["forecasts"] == 4
    expected = ((0.9 - 1) ** 2 + (0.2 - 1) ** 2 + (0.95 - 1) ** 2 + (0.1 - 1) ** 2) / 4
    assert acc["brier"] == pytest.approx(expected)
    assert acc["brier_first"] == pytest.approx(((0.9 - 1) ** 2 + (0.2 - 1) ** 2) / 2)
    assert acc["brier_matchup"] == pytest.approx(0.04)
    assert acc["likely_correct"] == pytest.approx(0.5)  # PTS calls right, REB calls wrong
    top = next(c for c in acc["calibration"] if c["range"] == "90-100%")
    # 0.9 and 0.95 on PTS came true, the 90% call against REB (p=0.1) didn't
    assert top["forecasts"] == 3 and top["actual"] == pytest.approx(2 / 3)
    assert forecast_accuracy(forecasts, {}) is None


def test_results_of_finished_matchups_are_recorded(tmp_path, today):
    store = SnapshotStore(tmp_path / "f.db")
    assert store.record_results(today) == 10  # 9 categories + the matchup
    store.record_forecast(today, 4, {"PTS": 0.7, "*": 0.6})
    forecasts, results = store.forecast_history(today.league.id, today.league.season)
    assert {cat for _, _, cat, _ in forecasts} == {"PTS", "*"}
    assert results[(4, "*")] in ("WIN", "LOSS", "TIE")
    assert all(period == 4 for period, _ in results)
    assert forecast_accuracy(forecasts, results)["forecasts"] == 1
