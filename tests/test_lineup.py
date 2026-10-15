import json

import httpx
import pytest

from fantasy.analysis.context import Context
from fantasy.analysis.lineup import lineup_check
from fantasy.cli import main
from fantasy.models import Player
from fantasy.notify import NotifyError, alert_text, send_telegram
from tests.conftest import RIGA
from tests.helpers import game, snapshot

PG, SG, C, UTIL, BE = 0, 1, 4, 11, 12


def test_demo_lineup_check_finds_the_benched_player_with_a_game(view, world):
    check = view["lineup"]
    planted = min(
        (world.players[world.rosters[1][i]] for i in range(8, 13)),
        key=lambda p: p.quality * p.base_min,
    )
    assert check["is_today"] and check["lost_games"] == 1
    assert check["best_starts"] == check["current_starts"] + 1
    (swap,) = check["swaps"]
    assert swap["start"] == planted.name and swap["for"] and swap["reason"] == "no game"
    assert check["lock"].endswith("02:30")


def _league(injured_starter: bool):
    players = [
        Player(id=1, name="Starter PG", pro_team_id=1, eligible_slots=[PG, UTIL]),
        Player(id=2, name="Idle C", pro_team_id=3, eligible_slots=[C, UTIL]),
        Player(id=3, name="Bench C", pro_team_id=2, eligible_slots=[C, UTIL]),
        Player(
            id=4,
            name="Hurt guard",
            pro_team_id=1,
            eligible_slots=[PG, UTIL],
            injury_status="OUT" if injured_starter else "DAY_TO_DAY",
        ),
    ]
    games = [game(1, 10, "2026-10-15T23:30:00+00:00", 1, 2)]
    roster = [(1, PG), (2, C), (3, BE), (4, UTIL)]
    snap = snapshot(players, roster, games, {PG: 1, C: 1, UTIL: 1, BE: 2}, sps=[10])
    return snap, Context.build(snap)


def test_idle_and_injured_starters_are_swapped_out():
    snap, ctx = _league(injured_starter=True)
    check = lineup_check(ctx, snap.team(1), RIGA, [])
    assert check["current_starts"] == 1  # only the PG plays and is healthy
    assert check["best_starts"] == 2  # Bench C into the C slot
    assert check["swaps"] == [
        {"start": "Bench C", "for": "Idle C", "reason": "no game", "slot": "C", "tipoff": "02:30"}
    ]
    assert check["bench"] == [{"name": "Hurt guard", "reason": "OUT"}]
    assert not check["ok"]


def test_day_to_day_starters_are_flagged_to_check():
    snap, ctx = _league(injured_starter=False)
    check = lineup_check(ctx, snap.team(1), RIGA, [])
    assert check["watch"] == ["Hurt guard (DTD)"]


def test_alert_text_lists_the_moves_and_stays_quiet_when_all_is_set(view):
    text = alert_text(view)
    assert text.startswith("Rembates Hektors IR: first lock 02:30")
    assert "Start " in text and "in " in text
    quiet = {"meta": view["meta"], "lineup": None, "changes": {"injuries": []}, "matchup": None}
    assert alert_text(quiet) is None
    assert "nothing to change" in alert_text(quiet, always=True)


def test_send_telegram_posts_the_message():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    send_telegram("123:ABC", "42", "hello", transport=httpx.MockTransport(handler))
    assert sent == [
        (
            "/bot123:ABC/sendMessage",
            {"chat_id": "42", "text": "hello", "disable_web_page_preview": True},
        )
    ]
    refused = httpx.MockTransport(
        lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    with pytest.raises(NotifyError, match="Unauthorized"):
        send_telegram("bad", "42", "hello", transport=refused)


def test_check_command_prints_the_alert_and_needs_telegram_to_notify(tmp_path, monkeypatch, capsys):
    for key in ("ESPN_LEAGUE_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FANTASY_PUNT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FANTASY_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("fantasy.config.PROJECT_DIR", tmp_path)
    assert main(["check", "--demo"]) == 0
    assert "first lock" in capsys.readouterr().out
    assert main(["check", "--demo", "--notify"]) == 1
    assert "Telegram is not set up" in capsys.readouterr().err
