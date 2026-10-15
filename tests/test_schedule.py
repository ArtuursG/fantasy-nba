from datetime import date

from fantasy.analysis.context import Context
from fantasy.analysis.schedule import (
    Lineup,
    back_to_backs,
    candidate_days,
    eligible_starting_slots,
    is_available,
    plan_days,
    starting_slots,
)
from fantasy.models import Player
from tests.helpers import game, snapshot

PG, SG, C, UTIL = 0, 1, 4, 11


def test_lineup_moves_flexible_players_to_fit_everyone():
    lineup = Lineup([PG, SG, C, UTIL])
    assert lineup.try_add(1, {PG, SG, UTIL})  # takes PG first
    assert lineup.try_add(2, {PG, UTIL})  # pushes player 1 over to SG
    assert lineup.try_add(3, {C, UTIL})
    assert lineup.try_add(4, {C, UTIL})  # UTIL
    assert not lineup.try_add(5, {C, UTIL})
    assert sorted(lineup.started) == [1, 2, 3, 4]
    assert lineup.open_slots == []


def test_fits_does_not_change_the_lineup():
    lineup = Lineup([PG, C])
    lineup.try_add(1, {PG})
    assert lineup.fits(2, {C})
    assert not lineup.fits(3, {PG})
    assert lineup.started == [1] and lineup.open_slots == [C]


def test_starting_slots_put_util_last_and_skip_bench_and_ir():
    assert starting_slots({11: 3, 0: 1, 4: 1, 12: 2, 13: 1}) == [0, 4, 11, 11, 11]


def test_eligibility_falls_back_to_default_position():
    assert eligible_starting_slots(Player(id=1, name="x", default_position="C")) == {C, UTIL}
    assert eligible_starting_slots(Player(id=1, name="x", eligible_slots=[0, 5, 11, 12, 13])) == {
        0,
        5,
        11,
    }


def test_out_player_is_available_from_his_return_date():
    player = Player(id=1, name="x", injury_status="OUT", expected_return="2026-10-16")
    assert not is_available(player, date(2026, 10, 15))
    assert is_available(player, date(2026, 10, 16))
    assert not is_available(Player(id=2, name="y", injury_status="OUT"), date(2027, 1, 1))
    assert is_available(Player(id=3, name="z", injury_status="DAY_TO_DAY"), date(2026, 10, 15))


def test_back_to_backs():
    days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16)]
    assert back_to_backs(days) == 2


def _league():
    players = [
        Player(id=1, name="Star PG", pro_team_id=1, eligible_slots=[PG, UTIL]),
        Player(id=2, name="Backup PG", pro_team_id=1, eligible_slots=[PG, UTIL]),
        Player(id=3, name="Center", pro_team_id=2, eligible_slots=[C, UTIL]),
        Player(id=4, name="Hurt C", pro_team_id=2, eligible_slots=[C, UTIL], injury_status="OUT"),
        Player(id=5, name="IR PG", pro_team_id=1, eligible_slots=[PG, UTIL]),
        Player(id=6, name="FA C", pro_team_id=5, eligible_slots=[C, UTIL]),
        Player(id=7, name="FA PG", pro_team_id=6, eligible_slots=[PG, UTIL]),
    ]
    games = [
        game(1, 9, "2026-10-14T23:30:00+00:00", 1, 2),  # yesterday: played
        game(2, 10, "2026-10-15T23:30:00+00:00", 1, 3),
        game(3, 10, "2026-10-15T23:30:00+00:00", 2, 4),
        game(4, 10, "2026-10-15T23:30:00+00:00", 6, 8),
        game(5, 11, "2026-10-16T23:30:00+00:00", 1, 9),
        game(6, 11, "2026-10-16T23:30:00+00:00", 5, 6),
    ]
    snap = snapshot(
        players,
        roster=[(1, 0), (2, 12), (3, 4), (4, 12), (5, 13)],
        games=games,
        lineup_slots={PG: 1, C: 1, UTIL: 1, 12: 3, 13: 1},
        sps=[9, 10, 11],
        free_agents=[6, 7],
    )
    return snap, Context.build(snap)


def test_plan_days_starts_the_best_available_players():
    snap, ctx = _league()
    values = {1: 3.0, 2: 1.0, 3: 2.0}
    plans = plan_days(ctx.calendar, snap, snap.team(1), values, ctx.sps, ctx.now)

    assert [p.sp for p in plans] == [10, 11]  # sp 9 already played
    today, tomorrow = plans
    assert sorted(today.started) == [1, 2, 3]
    assert today.unavailable == [4]  # OUT, and the IR-slot player is never counted
    assert today.open_slots == [] and today.benched == []
    assert sorted(tomorrow.started) == [1, 2] and tomorrow.open_slots == [C]

    played = plan_days(ctx.calendar, snap, snap.team(1), values, ctx.sps, ctx.now, remaining=False)
    assert [p.sp for p in played] == [9]


def test_free_agent_usable_only_where_he_fills_an_open_slot():
    snap, ctx = _league()
    plans = plan_days(ctx.calendar, snap, snap.team(1), {1: 3.0, 2: 1.0, 3: 2.0}, ctx.sps, ctx.now)

    with_game, usable = candidate_days(snap.players[6], plans, ctx.calendar, ctx.now)
    assert [p.sp for p in with_game] == [11] and [p.sp for p in usable] == [11]

    with_game, usable = candidate_days(snap.players[7], plans, ctx.calendar, ctx.now)
    assert [p.sp for p in with_game] == [10, 11]
    assert usable == []  # full on day 10, only C open on day 11
