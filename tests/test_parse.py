import pytest

from fantasy.espn.parse import (
    apply_injury_notes,
    find_team,
    merge_wrapper,
    parse_matchups,
    parse_pro_schedule,
    parse_stat_entries,
    parse_transactions,
)
from fantasy.models import Player, Team

SEASON = 2027


def _aggregate(source, split, season, stats, averages=None):
    entry = {
        "id": f"{source}{split}{season}",
        "externalId": str(season),
        "seasonId": season,
        "scoringPeriodId": 0,
        "statSourceId": source,
        "statSplitTypeId": split,
        "stats": stats,
    }
    if averages is not None:
        entry["averageStats"] = averages
    return entry


def test_stat_entries_split_into_aggregates_and_games():
    entries = [
        _aggregate(0, 0, SEASON, {"0": 200, "42": 10, "41": 8, "40": 320}, {"0": 20.0, "40": 32.0}),
        _aggregate(0, 1, SEASON, {"0": 60, "42": 3, "40": 90}),  # no averageStats
        _aggregate(1, 0, SEASON, {"0": 1500, "42": 70}, {"0": 21.4, "40": 33.5}),
        _aggregate(0, 0, SEASON - 1, {"0": 1300, "42": 65}, {"0": 20.0, "40": 31.0}),
        _aggregate(0, 0, SEASON - 2, {"0": 999, "42": 60}, {"0": 16.6}),  # too old, ignored
        {
            "id": "05401800001",
            "externalId": "401800001",
            "seasonId": SEASON,
            "scoringPeriodId": 12,
            "statSourceId": 0,
            "statSplitTypeId": 5,
            "proTeamId": 9,
            "stats": {"0": 25, "40": 34, "41": 1, "13": 9, "14": 18, "42": 1},
        },
        {  # a game with no stats line: not counted as played
            "id": "05401800002",
            "externalId": "401800002",
            "seasonId": SEASON,
            "scoringPeriodId": 14,
            "statSourceId": 0,
            "statSplitTypeId": 5,
            "stats": {},
        },
        {  # a projected single game: ignored
            "id": "15401800003",
            "externalId": "401800003",
            "seasonId": SEASON,
            "scoringPeriodId": 15,
            "statSourceId": 1,
            "statSplitTypeId": 5,
            "stats": {"0": 20},
        },
    ]
    splits, games = parse_stat_entries(entries, SEASON)

    assert set(splits) == {"season", "last7", "projected", "prev_season"}
    assert splits["season"].pts == 20.0 and splits["season"].min == 32.0
    assert splits["season"].gp == 10 and splits["season"].gs == 8
    assert splits["last7"].pts == 20.0  # 60 points over 3 games
    assert splits["last7"].min == 30.0
    assert splits["projected"].pts == 21.4
    assert splits["prev_season"].min == 31.0

    assert len(games) == 1
    game = games[0]
    assert (game.sp, game.team_id, game.started) == (12, 9, True)
    assert (game.line.pts, game.line.min, game.line.fgm, game.line.fga) == (25, 34, 9, 18)


def test_merge_wrapper_reads_ownership_ratings_and_return_date():
    players: dict[int, Player] = {}
    wrapper = {
        "id": 42,
        "onTeamId": 0,
        "status": "WAIVERS",
        "ratings": {
            "0": {"positionalRanking": 12, "totalRanking": 80, "totalRating": 3.21},
            "2": {"positionalRanking": 5, "totalRanking": 30, "totalRating": 6.5},
        },
        "player": {
            "id": 42,
            "fullName": "Test Guard",
            "proTeamId": 14,
            "defaultPositionId": 1,
            "eligibleSlots": [0, 5, 11, 12, 13],
            "injuryStatus": "OUT",
            "injuryDetails": {"expectedReturnDate": [2026, 11, 2]},
            "ownership": {"percentOwned": 12.5, "percentChange": 4.2, "percentStarted": 8.0},
            "draftRanksByRankType": {"STANDARD": {"rank": 140}},
            "stats": [],
        },
    }
    player = merge_wrapper(players, wrapper, SEASON)

    assert player is players[42]
    assert (player.name, player.pro_team_id, player.default_position) == ("Test Guard", 14, "PG")
    assert player.injury_status == "OUT"
    assert player.expected_return == "2026-11-02"
    assert (player.percent_owned, player.percent_change) == (12.5, 4.2)
    assert player.draft_rank == 140
    assert player.ratings["season"].rank == 80 and player.ratings["last15"].rating == 6.5
    assert player.pool_status == "WAIVERS" and player.on_team_id is None

    # A later player card fills in but doesn't overwrite who owns him.
    merge_wrapper(
        players, {"id": 42, "status": "ONTEAM", "onTeamId": 3, "player": {"id": 42}}, SEASON
    )
    assert player.pool_status == "WAIVERS"


def test_pro_schedule_dedupes_games_and_fixes_abbreviations():
    game = {
        "id": 1,
        "date": 1792800000000,
        "homeProTeamId": 9,
        "awayProTeamId": 26,
        "scoringPeriodId": 7,
    }
    raw = {
        "settings": {
            "proTeams": [
                {"id": 0, "abbrev": "FA", "proGamesByScoringPeriod": {}},
                {"id": 9, "abbrev": "GS", "proGamesByScoringPeriod": {"7": [game]}},
                {"id": 26, "abbrev": "Utah", "proGamesByScoringPeriod": {"7": [game]}},
            ]
        }
    }
    abbrevs, games = parse_pro_schedule(raw)
    assert abbrevs == {9: "GSW", 26: "UTA"}
    assert len(games) == 1 and games[0].sp == 7 and games[0].home_id == 9


def test_matchup_scores_by_category_and_percent_scale():
    raw = {
        "schedule": [
            {
                "matchupPeriodId": 3,
                "home": {
                    "teamId": 1,
                    "cumulativeScore": {
                        "wins": 5,
                        "losses": 3,
                        "ties": 1,
                        "scoreByStat": {
                            "19": {"score": 0.4921, "result": "WIN"},
                            "20": {"score": 82.9, "result": "WIN"},
                            "0": {"score": 571, "result": "WIN"},
                        },
                    },
                },
                "away": {"teamId": 2, "cumulativeScore": {"scoreByStat": {}}},
            },
            {"matchupPeriodId": 2, "home": {"teamId": 1}, "away": {"teamId": 3}},
        ]
    }
    (matchup,) = parse_matchups(raw, 3)
    assert matchup.home.stats == pytest.approx({"FG%": 0.4921, "FT%": 0.829, "PTS": 571.0})
    assert matchup.home.results["PTS"] == "WIN"
    assert (matchup.home.wins, matchup.home.losses, matchup.home.ties) == (5, 3, 1)
    assert matchup.away is not None and matchup.away.team_id == 2


def test_transactions_skip_cancelled_and_dedupe():
    base = {
        "id": "a",
        "type": "FREEAGENT",
        "status": "EXECUTED",
        "teamId": 4,
        "scoringPeriodId": 10,
        "processDate": 1792800000000,
        "items": [
            {"type": "ADD", "playerId": 7, "fromTeamId": 0, "toTeamId": 4},
            {"type": "DROP", "playerId": 8, "fromTeamId": 4, "toTeamId": 0},
            {"type": "LINEUP", "playerId": 9},
        ],
    }
    cancelled = dict(base, id="b", status="CANCELED")
    roster_move = dict(base, id="c", type="ROSTER")
    transactions = parse_transactions(
        [{"transactions": [base, cancelled, roster_move]}, {"transactions": [base]}]
    )
    assert [t.id for t in transactions] == ["a"]
    items = transactions[0].items
    assert [(i.type, i.player_id, i.to_team_id) for i in items] == [
        ("ADD", 7, 4),
        ("DROP", 8, None),
    ]


def test_injury_notes_match_by_link_id_then_name():
    players = {
        1: Player(id=1, name="Nikola Jokić", injury_status="OUT"),
        2: Player(id=2, name="Jaren Jackson Jr.", injury_status="DAY_TO_DAY"),
    }
    raw = {
        "injuries": [
            {
                "injuries": [
                    {
                        "athlete": {
                            "links": [{"href": "https://www.espn.com/nba/player/_/id/1/x"}]
                        },
                        "shortComment": "Out Friday.",
                        "date": "2026-10-14T18:00Z",
                        "details": {
                            "side": "Left",
                            "type": "Knee",
                            "detail": "Sprain",
                            "returnDate": "2026-10-20",
                        },
                    },
                    {
                        "athlete": {"displayName": "Jaren Jackson"},
                        "longComment": "Questionable.",
                        "details": {"side": "Not Specified", "type": "Ankle"},
                    },
                ]
            }
        ]
    }
    apply_injury_notes(players, raw)
    assert players[1].injury_note == "Left Knee Sprain: Out Friday."
    assert players[1].expected_return == "2026-10-20"
    assert players[1].injury_date == "2026-10-14"
    assert players[2].injury_note == "Ankle: Questionable."


def test_find_team_by_name_id_abbrev_and_unique_part():
    teams = [Team(id=1, name="Rembates Hektors IR", abbrev="RHIR"), Team(id=2, name="Bullu Kojas")]
    assert find_team(teams, "rembates  hektors ir") == 1
    assert find_team(teams, "2") == 2
    assert find_team(teams, "RHIR") == 1
    assert find_team(teams, "Kojas") == 2
    assert find_team(teams, "Nobody") is None


def test_demo_bundle_parses_into_a_full_snapshot(today, world):
    assert today.league.name.startswith("Wolfy Tribute Federation")
    assert today.league.categories == ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "TO", "PTS"]
    assert today.league.matchup_acquisition_limit == 5
    assert len(today.teams) == 10
    assert today.my_team_id == 1
    current = [m for m in today.matchups if m.period == today.league.matchup_period]
    assert len(current) == 5
    assert {m.period for m in today.matchups} == {4, 5, 6}  # last week final, next week
    assert all(m.winner != "UNDECIDED" for m in today.matchups if m.period == 4)
    assert any(today.players[p].pool_status == "WAIVERS" for p in today.free_agent_ids)
    my_roster = today.team(1).roster
    assert sum(1 for s in my_roster if s.slot_id == 13) == 1
    ir_player = today.players[world.ir[1]]
    assert ir_player.injury_note and ir_player.expected_return
    assert all(g.date for p in today.players.values() for g in p.games)
    assert {t.type for t in today.transactions} >= {"FREEAGENT", "WAIVER", "WAIVER_ERROR"}
    named = {today.player_name(i.player_id) for t in today.transactions for i in t.items}
    assert not any(n.startswith("Player ") for n in named)


def test_unknown_team_hint_is_a_warning(raw_today):
    from fantasy.espn.parse import parse_bundle

    snapshot = parse_bundle(raw_today, "No Such Team")
    assert snapshot.my_team_id is None
    assert "No Such Team" in snapshot.warnings[0]
