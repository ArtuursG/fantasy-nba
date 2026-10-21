"""Reads a league from ESPN's fantasy v3 API.

`fetch_bundle` makes every request a refresh needs and returns the raw
responses untouched; `parse.parse_bundle` turns them into a Snapshot. Keeping
the two apart means a raw bundle can be saved and parsed again later.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import httpx

from fantasy.espn.constants import FANTASY_BASE, INJURIES_URL, TRANSACTION_TYPES

USER_AGENT = "fantasy-report/0.1 (personal league snapshot)"
TIMEOUT = 30.0
MAX_RETRIES = 2
CARD_BATCH = 40  # what espn-api uses for player cards

LEAGUE_VIEWS = [
    "mTeam",
    "mRoster",
    "mSettings",
    "mStatus",
    "mMatchup",
    "mMatchupScore",
    "mScoreboard",
    "mPendingTransactions",
]


class EspnError(Exception):
    pass


class EspnAuthError(EspnError):
    pass


class EspnClient:
    def __init__(
        self,
        league_id: int,
        season: int,
        espn_s2: str | None = None,
        swid: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.league_id = league_id
        self.season = season
        cookies = {"espn_s2": espn_s2, "SWID": swid} if espn_s2 and swid else {}
        self._http = httpx.Client(
            cookies=cookies,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    @property
    def league_url(self) -> str:
        return f"{FANTASY_BASE}/seasons/{self.season}/segments/0/leagues/{self.league_id}"

    def league(
        self,
        views: Iterable[str],
        params: dict[str, Any] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        query = [("view", v) for v in views] + list((params or {}).items())
        return self._get(self.league_url, query, filters)

    def season_view(self, view: str) -> Any:
        return self._get(f"{FANTASY_BASE}/seasons/{self.season}", [("view", view)], None)

    def players_index(self) -> Any:
        return self._get(
            f"{FANTASY_BASE}/seasons/{self.season}/players",
            [("view", "players_wl")],
            {"filterActive": {"value": True}},
        )

    def injuries(self) -> Any:
        return self._get(INJURIES_URL, [], None)

    def _get(self, url: str, query: list[tuple[str, Any]], filters: dict[str, Any] | None) -> Any:
        headers = {"X-Fantasy-Filter": json.dumps(filters)} if filters else {}
        last_exc: httpx.TransportError | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._http.get(url, params=query, headers=headers)
                break
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(2**attempt)
        else:
            raise EspnError(f"Could not reach ESPN: {last_exc}") from last_exc

        if response.status_code in (401, 403):
            raise EspnAuthError(
                f"ESPN refused access (HTTP {response.status_code}). A private league needs "
                "ESPN_S2 and ESPN_SWID; check that both are current and that ESPN_LEAGUE_ID "
                "and ESPN_SEASON are right."
            )
        if response.status_code == 404:
            raise EspnError(
                f"ESPN returned 404 for {url}. Check ESPN_LEAGUE_ID and ESPN_SEASON "
                f"(season {self.season} means the NBA season ending in {self.season})."
            )
        if response.status_code != 200:
            raise EspnError(f"ESPN returned HTTP {response.status_code} for {url}")
        try:
            return response.json()
        except ValueError as exc:
            raise EspnError(f"ESPN sent a response that is not JSON for {url}") from exc


def split_ids(season: int) -> list[str]:
    """Aggregate stat splits to request: season, projection, last 7/15/30, last season."""
    return [
        f"00{season}",
        f"10{season}",
        f"01{season}",
        f"02{season}",
        f"03{season}",
        f"00{season - 1}",
    ]


def free_agent_filter(season: int, sp: int, limit: int, sort: str) -> dict[str, Any]:
    players: dict[str, Any] = {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "filterSlotIds": {"value": list(range(12))},
        "limit": limit,
        "offset": 0,
        sort: {"sortPriority": 1, "sortAsc": False},
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
        "filterRanksForScoringPeriodIds": {"value": [sp]},
        "filterRanksForRankTypes": {"value": ["STANDARD"]},
        "filterStatsForTopScoringPeriodIds": {"value": 2, "additionalValue": split_ids(season)},
    }
    return {"players": players}


def player_card_filter(player_ids: list[int], season: int, gamelog_days: int) -> dict[str, Any]:
    return {
        "players": {
            "filterIds": {"value": player_ids},
            "filterStatsForTopScoringPeriodIds": {
                "value": gamelog_days,
                "additionalValue": split_ids(season),
            },
        }
    }


def transactions_filter() -> dict[str, Any]:
    return {"transactions": {"filterType": {"value": TRANSACTION_TYPES}}}


def rostered_player_ids(league: dict[str, Any]) -> list[int]:
    ids = []
    for team in league.get("teams") or []:
        for entry in (team.get("roster") or {}).get("entries") or []:
            if entry.get("playerId"):
                ids.append(int(entry["playerId"]))
    return ids


def pool_player_ids(response: Any) -> list[int]:
    ids = []
    for wrapper in (response or {}).get("players") or []:
        player_id = wrapper.get("id") or (wrapper.get("player") or {}).get("id")
        if player_id:
            ids.append(int(player_id))
    return ids


def fetch_bundle(
    client: EspnClient,
    *,
    gamelog_days: int = 30,
    fa_pool: int = 150,
    transaction_days: int = 7,
    log: Callable[[str], None] = lambda _msg: None,
) -> dict[str, Any]:
    """Every response one refresh needs, keyed by what it is."""
    season = client.season
    raw: dict[str, Any] = {
        "meta": {
            "fetched_at": datetime.now(UTC).isoformat(),
            "league_id": client.league_id,
            "season": season,
        },
        "warnings": [],
    }

    log("league, rosters, settings and matchups")
    league = client.league(LEAGUE_VIEWS)
    raw["league"] = league
    sp = int(league.get("scoringPeriodId") or 1)

    log("live matchup scores")
    period = int((league.get("status") or {}).get("currentMatchupPeriod") or 0)
    try:
        # What ESPN's own scoreboard asks for: the general league response
        # can lag behind on the current week's category totals.
        raw["scoreboard"] = client.league(
            ["mMatchupScore", "mScoreboard"],
            params={"scoringPeriodId": sp},
            filters={"schedule": {"filterMatchupPeriodIds": {"value": [period]}}},
        )
    except EspnError as exc:
        raw["warnings"].append(f"Live matchup scores unavailable: {exc}")

    log("NBA schedule")
    raw["pro_schedule"] = client.season_view("proTeamSchedules_wl")

    log("free agents")
    raw["free_agents"] = client.league(
        ["kona_player_info"],
        params={"scoringPeriodId": sp},
        filters=free_agent_filter(season, sp, fa_pool, "sortPercOwned"),
    )
    try:
        raw["free_agents_trending"] = client.league(
            ["kona_player_info"],
            params={"scoringPeriodId": sp},
            filters=free_agent_filter(season, sp, 50, "sortPercChanged"),
        )
    except EspnError as exc:
        raw["warnings"].append(f"Trending free agents unavailable: {exc}")

    ids = list(
        dict.fromkeys(
            rostered_player_ids(league)
            + pool_player_ids(raw["free_agents"])
            + pool_player_ids(raw.get("free_agents_trending"))
        )
    )
    log(f"game logs for {len(ids)} players")
    raw["player_cards"] = [
        client.league(
            ["kona_playercard"],
            filters=player_card_filter(ids[i : i + CARD_BATCH], season, gamelog_days),
        )
        for i in range(0, len(ids), CARD_BATCH)
    ]

    log("league transactions")
    raw["transactions"] = []
    for period in range(max(1, sp - transaction_days), sp + 1):
        try:
            raw["transactions"].append(
                client.league(
                    ["mTransactions2"],
                    params={"scoringPeriodId": period},
                    filters=transactions_filter(),
                )
            )
        except EspnError as exc:
            raw["warnings"].append(f"Transactions for scoring period {period} unavailable: {exc}")

    log("player names")
    try:
        raw["players_index"] = client.players_index()
    except EspnError as exc:
        raw["warnings"].append(f"Player index unavailable: {exc}")

    log("injury notes")
    try:
        raw["injuries"] = client.injuries()
    except EspnError as exc:
        raw["warnings"].append(f"Injury notes unavailable: {exc}")

    return raw
