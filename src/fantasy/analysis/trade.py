"""Trades: who to target, and what a proposed trade would do.

Targets: with a punt, players worth more to me than to the league (their
value without the punted categories beats their value with them) on other
teams to buy, and mine worth more to others to sell; always, players on
other teams strong in my weakest categories.

Evaluation: both rosters' per-game category output and league ranks
before and after, the players' value both ways, the rest of this
matchup re-projected with the new roster, and the roster-size and center
checks a trade has to pass.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations

from fantasy.analysis.context import Context
from fantasy.analysis.matchup import (
    category_outlook,
    matchup_outlook,
    project_side,
    sides_for,
    team_strength,
)
from fantasy.analysis.schedule import positions, starting_slots
from fantasy.analysis.season import GAMES_PER_SLOT_PER_WEEK, _cat_odds
from fantasy.espn.constants import BENCH_SLOT, C_SLOT, IR_SLOT, UNAVAILABLE_STATUSES
from fantasy.models import COUNTING_FIELDS, RosterSpot

PUNT_EDGE = 0.1
NEEDS = 3


class TradeError(Exception):
    pass


def _values(ctx: Context, pid: int) -> tuple[float, float]:
    line = ctx.lines[pid]
    return ctx.valuation.mean(line, ctx.punt), ctx.valuation.mean(line)


def _player(ctx: Context, pid: int) -> dict:
    value, league_value = _values(ctx, pid)
    player = ctx.snap.players[pid]
    return {
        "id": pid,
        "name": player.name,
        "pro_team": player.pro_team,
        "positions": "/".join(positions(player)),
        "owner": ctx.owner_label(player),
        "value": round(value, 2),
        "league_value": round(league_value, 2),
    }


def trade_targets(ctx: Context, strength: dict[int, dict]) -> dict:
    me = ctx.my_team
    if me is None:
        return {"buy": [], "sell": [], "needs": [], "need_targets": []}
    mine = {s.player_id for s in me.roster}
    others = [
        s.player_id
        for t in ctx.snap.teams
        if t.id != me.id
        for s in t.roster
        if s.slot_id != IR_SLOT
    ]
    my_values = sorted(_values(ctx, pid)[0] for pid in mine)
    floor = my_values[len(my_values) // 2] if my_values else 0.0

    buy, sell = [], []
    if ctx.punt:
        for pid in others:
            value, league_value = _values(ctx, pid)
            if value - league_value >= PUNT_EDGE and value >= floor:
                buy.append({**_player(ctx, pid), "edge": round(value - league_value, 2)})
        for pid in mine:
            value, league_value = _values(ctx, pid)
            # Only players other managers would actually want are worth shopping.
            if league_value - value >= PUNT_EDGE and league_value >= max(floor, 0.0):
                sell.append({**_player(ctx, pid), "edge": round(league_value - value, 2)})
        buy.sort(key=lambda r: -(r["edge"] + r["value"]))
        sell.sort(key=lambda r: -r["edge"])

    ranks = strength.get(me.id, {}).get("ranks", {})
    needs = [cat for cat, _ in sorted(ranks.items(), key=lambda kv: -kv[1]) if cat not in ctx.punt][
        :NEEDS
    ]
    need_targets = []
    for pid in others:
        z = ctx.valuation.by_cat(ctx.lines[pid])
        fit = sum(z.get(c, 0.0) for c in needs)
        if fit > 0 and _values(ctx, pid)[0] >= floor:
            need_targets.append({**_player(ctx, pid), "fit": round(fit, 2)})
    need_targets.sort(key=lambda r: -r["fit"])
    return {
        "buy": buy[:10],
        "sell": sell[:5],
        "needs": needs,
        "need_targets": need_targets[:10],
    }


def evaluate_trade(ctx: Context, give: list[int], get: list[int]) -> dict:
    me = ctx.my_team
    if me is None:
        raise TradeError("Your team isn't in the league data.")
    mine = {s.player_id for s in me.roster}
    if not give or not get:
        raise TradeError("Pick at least one player to give and one to get.")
    if not set(give) <= mine:
        raise TradeError("You can only give players from your own roster.")
    owners = {ctx.snap.players[pid].on_team_id for pid in get if pid in ctx.snap.players}
    if len(owners) != 1 or None in owners or me.id in owners:
        raise TradeError("Players to get must all come from one other team.")
    other = ctx.snap.team(owners.pop())
    assert other is not None

    def active(team_roster: list[RosterSpot]) -> list[int]:
        return [s.player_id for s in team_roster if s.slot_id != IR_SLOT]

    my_after = [pid for pid in active(me.roster) if pid not in give] + list(get)
    their_after = [pid for pid in active(other.roster) if pid not in get] + list(give)
    before = team_strength(ctx)
    after = team_strength(ctx, {me.id: my_after, other.id: their_after})

    def compare(team_id: int) -> list[dict]:
        return [
            {
                "cat": cat,
                "before": before[team_id]["values"].get(cat),
                "after": after[team_id]["values"].get(cat),
                "rank_before": before[team_id]["ranks"].get(cat),
                "rank_after": after[team_id]["ranks"].get(cat),
            }
            for cat in ctx.snap.league.categories
        ]

    give_value = sum(_values(ctx, pid)[0] for pid in give)
    get_value = sum(_values(ctx, pid)[0] for pid in get)
    give_league = sum(_values(ctx, pid)[1] for pid in give)
    get_league = sum(_values(ctx, pid)[1] for pid in get)

    matchup = None
    opp_id = ctx.opponent_id(me.id)
    if opp_id is not None and ctx.snap.team(opp_id):
        my_side, opp_side = sides_for(ctx, me.id)
        opp = ctx.snap.team(opp_id)
        assert opp is not None
        now_mine = project_side(ctx, me, my_side)
        now_theirs = project_side(ctx, opp, opp_side)

        def swapped(team, ids):
            roster = [RosterSpot(pid, BENCH_SLOT) for pid in ids]
            roster += [s for s in team.roster if s.slot_id == IR_SLOT]
            return replace(team, roster=roster)

        new_mine = project_side(ctx, swapped(me, my_after), my_side, elapsed=now_mine.elapsed)
        new_theirs = now_theirs
        if opp.id == other.id:
            new_theirs = project_side(
                ctx, swapped(opp, their_after), opp_side, elapsed=now_theirs.elapsed
            )

        def outlook(a, b):
            rows = [o for c in ctx.snap.league.categories if (o := category_outlook(c, a, b))]
            return matchup_outlook(rows)

        base, new = outlook(now_mine, now_theirs), outlook(new_mine, new_theirs)
        matchup = {
            "expected_before": base["expected_wins"],
            "expected_after": new["expected_wins"],
            "p_win_before": base["p_win_matchup"],
            "p_win_after": new["p_win_matchup"],
        }

    centers = sum(
        1
        for pid in my_after + [s.player_id for s in me.roster if s.slot_id == IR_SLOT]
        if C_SLOT in ctx.snap.players[pid].eligible_slots
    )
    warnings = []
    if len(get) > len(give):
        warnings.append(f"You receive {len(get) - len(give)} more player(s): drop someone first.")
    if len(give) > len(get):
        warnings.append(f"{other.name} has to drop {len(give) - len(get)} player(s) to fit them.")
    if centers > ctx.snap.league.c_limit:
        warnings.append(
            f"You'd have {centers} C-eligible players (limit {ctx.snap.league.c_limit})."
        )

    return {
        "partner": other.name,
        "give": [_player(ctx, pid) for pid in give],
        "get": [_player(ctx, pid) for pid in get],
        "value_change": round(get_value - give_value, 2),
        "league_value_change": round(get_league - give_league, 2),
        "partner_value_change": round(give_league - get_league, 2),
        "mine": compare(me.id),
        "theirs": compare(other.id),
        "avg_rank_before": _avg(before[me.id]["ranks"], ctx.punt),
        "avg_rank_after": _avg(after[me.id]["ranks"], ctx.punt),
        "matchup": matchup,
        "warnings": warnings,
    }


def weekly_categories(
    ctx: Context, rosters: dict[int, list[int]] | None = None
) -> dict[int, float]:
    """Categories each team would expect to win in a week against the rest
    of the league, one opponent after another, with its best healthy
    players starting. `rosters` replaces some teams' players.

    Unlike a rank, this knows how big a lead or a gap is: giving up threes
    costs little while the lead in them is large, and catching up in steals
    is worth most when the gap is small.
    """
    snap = ctx.snap
    slots = len(starting_slots(snap.league.lineup_slots))
    games = slots * GAMES_PER_SLOT_PER_WEEK
    weeks: dict[int, dict[str, float]] = {}
    for team in snap.teams:
        ids = (rosters or {}).get(team.id) or [
            s.player_id for s in team.roster if s.slot_id != IR_SLOT
        ]
        healthy = [
            pid
            for pid in ids
            if pid in ctx.lines and snap.players[pid].injury_status not in UNAVAILABLE_STATUSES
        ]
        best = sorted(healthy, key=lambda pid: -ctx.values.get(pid, 0.0))[:slots]
        weeks[team.id] = {
            name: sum(getattr(ctx.lines[pid], name) for pid in best) / max(len(best), 1)
            for name in COUNTING_FIELDS
        }
    cats = [c for c in snap.league.categories if c not in ctx.punt]
    return {
        team_id: sum(
            _cat_odds(week, other, games, cat)
            for other_id, other in weeks.items()
            if other_id != team_id
            for cat in cats
        )
        / max(len(weeks) - 1, 1)
        for team_id, week in weeks.items()
    }


def _avg(ranks: dict[str, int], punt: tuple[str, ...]) -> float | None:
    counted = [r for c, r in ranks.items() if c not in punt]
    return round(sum(counted) / len(counted), 2) if counted else None


# Trade finder

BASE_NEED = 0.15
MIN_MY_GAIN = 0.15
MIN_THEIR_GAIN = 0.05
MAX_PARTNER_VALUE_LOSS = 0.25
SHORTLIST = 90
SHORTLIST_PER_PARTNER = 10
# Expected categories a week against the league: what a trade has to add
# for me, and the most it may cost the partner (rounding room, no more).
MIN_WEEKLY_GAIN = 0.1
MAX_PARTNER_WEEKLY_LOSS = 0.02
IDEAS = 8
PER_PARTNER = 2


def _needs(ranks: dict[str, int], punt: tuple[str, ...] = ()) -> dict[str, float]:
    """Weight per category: little where a team is already top-3, most where
    it ranks last."""
    return {cat: BASE_NEED + max(0, rank - 3) / 7 for cat, rank in ranks.items() if cat not in punt}


def _fit(z: dict[int, dict[str, float]], needs: dict[str, float], gets, gives) -> float:
    return sum(
        w * (sum(z[p].get(cat, 0.0) for p in gets) - sum(z[p].get(cat, 0.0) for p in gives))
        for cat, w in needs.items()
    )


def find_trades(ctx: Context, strength: dict[int, dict]) -> list[dict]:
    """1-for-1 and 2-for-1 trades that help both teams.

    A quick needs-weighted score picks a shortlist (a spot freed by a 2-for-1
    counts as a replacement-level pickup, the partner drops his weakest
    player). The exact evaluation then keeps the trades after which I'd
    expect to win more categories a week against the league and the partner
    no fewer (`weekly_categories`), best for me first: a trade he loses by
    is one he won't make.
    """
    snap = ctx.snap
    me = ctx.my_team
    if me is None:
        return []
    active = {
        t.id: [s.player_id for s in t.roster if s.slot_id != IR_SLOT and s.player_id in ctx.lines]
        for t in snap.teams
    }
    z = {pid: ctx.valuation.by_cat(ctx.lines[pid]) for ps in active.values() for pid in ps}
    value = {pid: ctx.valuation.mean(ctx.lines[pid]) for pid in z}
    my_needs = _needs(strength[me.id]["ranks"], ctx.punt)

    scored = []
    mine = active[me.id]
    for team in snap.teams:
        if team.id == me.id:
            continue
        their_needs = _needs(strength[team.id]["ranks"])
        theirs = active[team.id]
        weakest = min(theirs, key=lambda p: value[p], default=None)
        for get in theirs:
            for size in (1, 2):
                for give in combinations(mine, size):
                    gives, gets = list(give), [get]
                    their_drop = [weakest] if size == 2 and weakest is not None else []
                    my_gain = _fit(z, my_needs, gets, gives)
                    their_gain = _fit(z, their_needs, gives, gets + their_drop)
                    partner_value = (
                        sum(value[p] for p in gives)
                        - value[get]
                        - sum(value[p] for p in their_drop)
                    )
                    if (
                        my_gain >= MIN_MY_GAIN
                        and their_gain >= MIN_THEIR_GAIN
                        and partner_value >= -MAX_PARTNER_VALUE_LOSS
                    ):
                        scored.append((my_gain + 0.5 * their_gain, team, gives, gets))
    scored.sort(key=lambda s: -s[0])

    shortlist, per_partner = [], {}
    for item in scored:
        team = item[1]
        if per_partner.get(team.id, 0) < SHORTLIST_PER_PARTNER:
            per_partner[team.id] = per_partner.get(team.id, 0) + 1
            shortlist.append(item)
        if len(shortlist) == SHORTLIST:
            break

    ideas = []
    weekly = weekly_categories(ctx)
    for _, team, gives, gets in shortlist:
        new = weekly_categories(
            ctx,
            {
                me.id: [pid for pid in mine if pid not in gives] + gets,
                team.id: [pid for pid in active[team.id] if pid not in gets] + gives,
            },
        )
        if (
            new[me.id] - weekly[me.id] < MIN_WEEKLY_GAIN
            or new[team.id] - weekly[team.id] < -MAX_PARTNER_WEEKLY_LOSS
        ):
            continue
        exact = evaluate_trade(ctx, gives, gets)
        before, after = exact["avg_rank_before"], exact["avg_rank_after"]
        theirs_before = _mean([r["rank_before"] for r in exact["theirs"]])
        theirs_after = _mean([r["rank_after"] for r in exact["theirs"]])
        ideas.append(
            {
                "partner": team.name,
                "partner_id": team.id,
                "give": exact["give"],
                "get": exact["get"],
                "weekly_before": round(weekly[me.id], 2),
                "weekly_after": round(new[me.id], 2),
                "partner_weekly_before": round(weekly[team.id], 2),
                "partner_weekly_after": round(new[team.id], 2),
                "avg_rank_before": before,
                "avg_rank_after": after,
                "partner_rank_before": round(theirs_before, 2),
                "partner_rank_after": round(theirs_after, 2),
                "value_change": exact["value_change"],
                "partner_value_change": exact["partner_value_change"],
                "matchup": exact["matchup"],
                "warnings": exact["warnings"],
                "helps_me": _helped(z, my_needs, gets, gives),
                "helps_them": _helped(z, _needs(strength[team.id]["ranks"]), gives, gets),
            }
        )
    ideas.sort(
        key=lambda i: (
            i["weekly_before"] - i["weekly_after"],
            i["partner_weekly_before"] - i["partner_weekly_after"],
        )
    )
    out, per_partner = [], {}
    for idea in ideas:
        if per_partner.get(idea["partner_id"], 0) >= PER_PARTNER:
            continue
        per_partner[idea["partner_id"]] = per_partner.get(idea["partner_id"], 0) + 1
        out.append(idea)
        if len(out) == IDEAS:
            break
    return out


def _mean(values: list[int | None]) -> float:
    counted = [v for v in values if v is not None]
    return sum(counted) / len(counted) if counted else 0.0


def _helped(z, needs: dict[str, float], gets: list[int], gives: list[int]) -> list[str]:
    deltas = {
        cat: sum(z[p].get(cat, 0.0) for p in gets) - sum(z[p].get(cat, 0.0) for p in gives)
        for cat in needs
    }
    return [cat for cat, d in sorted(deltas.items(), key=lambda kv: -kv[1]) if d > 0.3][:4]
