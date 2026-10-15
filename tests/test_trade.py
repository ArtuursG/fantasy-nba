import pytest

from fantasy.analysis.context import Context
from fantasy.analysis.trade import TradeError, evaluate_trade


def test_trade_targets_follow_the_punt(snapshots):
    from fantasy.analysis.view import build_view
    from tests.conftest import RIGA

    week, yesterday, today = snapshots
    tt = build_view(today, yesterday, week, RIGA, punt=("TO",))["trade_targets"]
    mine = {s.player_id for s in today.team(1).roster}
    for row in tt["buy"]:
        assert row["id"] not in mine and row["value"] - row["league_value"] >= 0.1 - 1e-9
    for row in tt["sell"]:
        assert row["id"] in mine and row["league_value"] - row["value"] >= 0.1 - 1e-9
    assert "TO" not in tt["needs"] and len(tt["needs"]) == 3
    assert all(r["id"] not in mine for r in tt["need_targets"])


def test_evaluate_trade_reports_both_sides(today):
    ctx = Context.build(today, ("TO",))
    mine = [s.player_id for s in today.team(1).roster if s.slot_id != 13]
    theirs = [s.player_id for s in today.team(4).roster if s.slot_id != 13]
    give = sorted(mine, key=lambda p: ctx.values[p])[:1]
    get = sorted(theirs, key=lambda p: -ctx.values[p])[:1]
    result = evaluate_trade(ctx, give, get)
    assert result["partner"] == today.team(4).name
    assert result["value_change"] > 0  # their best for my worst
    assert len(result["mine"]) == 9 and result["matchup"] is not None
    assert result["matchup"]["expected_after"] >= result["matchup"]["expected_before"] - 0.5
    assert result["warnings"] == []
    two_for_one = evaluate_trade(ctx, give, sorted(theirs, key=lambda p: -ctx.values[p])[:2])
    assert any("drop someone" in w for w in two_for_one["warnings"])


def test_invalid_trades_are_explained(today):
    ctx = Context.build(today)
    mine = [s.player_id for s in today.team(1).roster]
    with pytest.raises(TradeError, match="own roster"):
        evaluate_trade(
            ctx, [today.team(2).roster[0].player_id], [today.team(3).roster[0].player_id]
        )
    with pytest.raises(TradeError, match="one other team"):
        evaluate_trade(
            ctx, mine[:1], [today.team(2).roster[0].player_id, today.team(3).roster[0].player_id]
        )
    with pytest.raises(TradeError, match="at least one"):
        evaluate_trade(ctx, [], [today.team(2).roster[0].player_id])
