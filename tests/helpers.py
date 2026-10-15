"""Small hand-built snapshots for unit tests."""

from fantasy.espn.constants import DEFAULT_CATEGORIES
from fantasy.models import League, Player, ProGame, RosterSpot, Snapshot, Team
from fantasy.timeutil import eastern_date

FETCHED_AT = "2026-10-15T16:00:00+00:00"


def game(game_id: int, sp: int, start: str, home: int, away: int) -> ProGame:
    return ProGame(
        id=game_id,
        sp=sp,
        start=start,
        date=eastern_date(start).isoformat(),
        home_id=home,
        away_id=away,
    )


def snapshot(
    players: list[Player],
    roster: list[tuple[int, int]],
    games: list[ProGame],
    lineup_slots: dict[int, int],
    sps: list[int],
    free_agents: list[int] | None = None,
) -> Snapshot:
    league = League(
        id=1,
        season=2027,
        name="Test league",
        size=2,
        categories=list(DEFAULT_CATEGORIES),
        lineup_slots=lineup_slots,
        scoring_period=sps[0],
        matchup_period=1,
        matchup_periods={1: sps},
    )
    mine = Team(id=1, name="Mine", roster=[RosterSpot(pid, slot) for pid, slot in roster])
    for player in players:
        if any(pid == player.id for pid, _ in roster):
            player.pool_status, player.on_team_id = "ONTEAM", 1
    return Snapshot(
        fetched_at=FETCHED_AT,
        league=league,
        my_team_id=1,
        teams=[mine, Team(id=2, name="Theirs")],
        players={p.id: p for p in players},
        free_agent_ids=free_agents or [],
        matchups=[],
        transactions=[],
        pro_games=games,
        pro_teams={},
    )
