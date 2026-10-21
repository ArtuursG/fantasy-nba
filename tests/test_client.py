import json

import httpx
import pytest

from fantasy.espn.client import EspnAuthError, EspnClient, EspnError, fetch_bundle
from fantasy.espn.parse import parse_bundle


def _serve_demo(raw: dict, calls: list):
    """A fake ESPN answering from a demo bundle, recording each request."""

    def handler(request: httpx.Request) -> httpx.Response:
        views = request.url.params.get_list("view")
        filters = json.loads(request.headers.get("x-fantasy-filter", "{}"))
        calls.append((request.url.path, views, filters, request.headers.get("cookie")))
        path = request.url.path
        if path.endswith("/injuries"):
            return httpx.Response(200, json=raw["injuries"])
        if path.endswith("/players"):
            return httpx.Response(200, json=raw["players_index"])
        if "proTeamSchedules_wl" in views:
            return httpx.Response(200, json=raw["pro_schedule"])
        if "kona_player_info" in views:
            key = (
                "free_agents_trending" if "sortPercChanged" in filters["players"] else "free_agents"
            )
            return httpx.Response(200, json=raw[key])
        if "kona_playercard" in views:
            wanted = set(filters["players"]["filterIds"]["value"])
            cards = [w for c in raw["player_cards"] for w in c["players"] if w["id"] in wanted]
            return httpx.Response(200, json={"players": cards})
        if "mTransactions2" in views:
            return httpx.Response(200, json=raw["transactions"][0])
        if "mTeam" in views:
            return httpx.Response(200, json=raw["league"])
        if "mScoreboard" in views:
            period = filters["schedule"]["filterMatchupPeriodIds"]["value"][0]
            schedule = [m for m in raw["league"]["schedule"] if m["matchupPeriodId"] == period]
            return httpx.Response(200, json={"schedule": schedule})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_fetch_bundle_makes_the_expected_requests(raw_today):
    calls: list = []
    client = EspnClient(
        424242, 2027, espn_s2="s2cookie", swid="{SWID}", transport=_serve_demo(raw_today, calls)
    )
    raw = fetch_bundle(client, gamelog_days=30, fa_pool=150)
    client.close()

    league_call = calls[0]
    assert league_call[0] == "/apis/v3/games/fba/seasons/2027/segments/0/leagues/424242"
    assert {"mTeam", "mRoster", "mSettings", "mMatchupScore"} <= set(league_call[1])
    assert "espn_s2=s2cookie" in league_call[3] and "SWID={SWID}" in league_call[3]

    board = next(c for c in calls if "mScoreboard" in c[1] and "mTeam" not in c[1])
    assert board[2]["schedule"]["filterMatchupPeriodIds"]["value"]
    assert raw["scoreboard"]["schedule"] and not raw["warnings"]

    card_calls = [c for c in calls if "kona_playercard" in c[1]]
    requested = [i for c in card_calls for i in c[2]["players"]["filterIds"]["value"]]
    assert all(len(c[2]["players"]["filterIds"]["value"]) <= 40 for c in card_calls)
    assert len(requested) == len(set(requested))
    stats_filter = card_calls[0][2]["players"]["filterStatsForTopScoringPeriodIds"]
    assert stats_filter["value"] == 30
    assert stats_filter["additionalValue"] == [
        "002027",
        "102027",
        "012027",
        "022027",
        "032027",
        "002026",
    ]
    assert len([c for c in calls if "mTransactions2" in c[1]]) == 8
    assert raw["warnings"] == []

    snapshot = parse_bundle(raw, "Home Team")
    assert snapshot.my_team_id == 1
    rostered = {s.player_id for t in snapshot.teams for s in t.roster}
    assert all(snapshot.players[p].games for p in rostered if snapshot.players[p].stats)


def test_private_league_without_cookies_is_explained():
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    client = EspnClient(1, 2027, transport=transport)
    with pytest.raises(EspnAuthError, match="ESPN_S2 and ESPN_SWID"):
        client.league(["mTeam"])


def test_missing_league_is_explained():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    client = EspnClient(1, 2027, transport=transport)
    with pytest.raises(EspnError, match="ESPN_LEAGUE_ID"):
        client.league(["mTeam"])


def test_optional_requests_fail_softly(raw_today):
    calls: list = []
    inner = _serve_demo(raw_today, calls)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/injuries"):
            return httpx.Response(503)
        return inner.handle_request(request)

    client = EspnClient(424242, 2027, transport=httpx.MockTransport(handler))
    raw = fetch_bundle(client)
    assert "injuries" not in raw
    assert raw["warnings"] and "Injury notes" in raw["warnings"][0]


def test_live_scoreboard_scores_win_over_the_league_response(raw_today):
    import copy

    from fantasy.espn.parse import parse_bundle

    raw = copy.deepcopy(raw_today)
    period = raw["league"]["status"]["currentMatchupPeriod"]
    live = copy.deepcopy([m for m in raw["league"]["schedule"] if m["matchupPeriodId"] == period])
    live[0]["home"]["cumulativeScore"] = {
        "wins": 8,
        "losses": 1,
        "ties": 0,
        "scoreByStat": {"0": {"score": 86, "result": "WIN"}},
    }
    raw["scoreboard"] = {"schedule": live}
    snap = parse_bundle(raw, "Home Team")
    home = next(
        m.home
        for m in snap.matchups
        if m.period == period and m.home.team_id == live[0]["home"]["teamId"]
    )
    assert (home.wins, home.losses, home.stats["PTS"]) == (8, 1, 86)
