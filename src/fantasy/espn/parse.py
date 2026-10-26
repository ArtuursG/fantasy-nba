"""Raw ESPN responses (see client.fetch_bundle) -> models.Snapshot.

ESPN omits fields freely, so every lookup tolerates absence. Where a value
can come from several responses (a rostered player appears in the roster,
in a player card and sometimes in the free-agent list) later sources fill
in or refresh the same Player instead of creating a second one.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from fantasy.espn.constants import (
    BENCH_SLOT,
    DEFAULT_CATEGORIES,
    DEFAULT_LINEUP_SLOTS,
    DEFAULT_POSITIONS,
    NON_STARTING_SLOTS,
    PRO_TEAMS,
    RATING_KEYS,
    SPLIT_KEYS,
    STAT_FIELDS,
    STAT_GP,
    STAT_GS,
    STAT_NAMES,
    TRANSACTION_TYPES,
)
from fantasy.models import (
    Game,
    League,
    Matchup,
    MatchupSide,
    Player,
    ProGame,
    Rating,
    RosterSpot,
    Snapshot,
    StatLine,
    Team,
    Transaction,
    TransactionItem,
)
from fantasy.timeutil import date_for_sp, eastern_date, ms_to_iso, parse_iso, sp_dates_from

# ESPN's own short forms -> the abbreviations most NBA readers expect.
ABBREV_FIXES = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
    "PHL": "PHI",
    "PHO": "PHX",
    "BRK": "BKN",
    "CHO": "CHA",
}
PERCENT_STATS = {"FG%", "FT%", "3P%"}
KEPT_ITEM_TYPES = {"ADD", "DROP", "TRADE"}


def parse_bundle(raw: dict[str, Any], team_hint: str | None, demo: bool = False) -> Snapshot:
    league_raw = raw["league"]
    meta = raw.get("meta") or {}
    warnings = list(raw.get("warnings") or [])

    league = parse_league(league_raw, meta)
    season = league.season
    pro_teams, pro_games = parse_pro_schedule(raw.get("pro_schedule"))
    sp_dates = sp_dates_from((g.sp, g.date) for g in pro_games)
    league.matchup_periods = matchup_scoring_periods(
        league.matchup_periods, sp_dates, league.first_scoring_period, league.final_scoring_period
    )

    players: dict[int, Player] = {}
    teams = parse_teams(league_raw, players, season)

    free_agent_ids: list[int] = []
    for key in ("free_agents", "free_agents_trending"):
        for wrapper in (raw.get(key) or {}).get("players") or []:
            player = merge_wrapper(players, wrapper, season)
            if (
                player
                and player.pool_status in ("FREEAGENT", "WAIVERS")
                and player.id not in free_agent_ids
            ):
                free_agent_ids.append(player.id)
    for card in raw.get("player_cards") or []:
        for wrapper in (card or {}).get("players") or []:
            merge_wrapper(players, wrapper, season)

    transactions = parse_transactions(raw.get("transactions") or [])
    add_index_players(players, raw.get("players_index"), transactions)
    apply_injury_notes(players, raw.get("injuries"))

    for player in players.values():
        player.pro_team = pro_teams.get(player.pro_team_id) or PRO_TEAMS.get(
            player.pro_team_id, "FA"
        )
        for game in player.games:
            day = date_for_sp(sp_dates, game.sp)
            game.date = day.isoformat() if day else ""
        player.games.sort(key=lambda g: g.sp)

    estimate_waiver_clear(players, free_agent_ids, transactions, league.waiver_hours)

    my_team_id = find_team(teams, team_hint)
    if team_hint and my_team_id is None:
        names = ", ".join(t.name for t in teams) or "none"
        warnings.append(f"Team '{team_hint}' not found in the league. Teams: {names}.")

    return Snapshot(
        fetched_at=meta.get("fetched_at") or "",
        league=league,
        my_team_id=my_team_id,
        teams=teams,
        players=players,
        free_agent_ids=free_agent_ids,
        matchups=apply_lineup_totals(
            merge_live_scores(
                parse_matchups(league_raw, league.matchup_period, around=1),
                parse_matchups(raw.get("scoreboard") or {}, league.matchup_period),
            ),
            lineup_totals(
                raw.get("daily_rosters") or {},
                players,
                season,
                league.matchup_periods.get(league.matchup_period) or [],
            ),
            league,
        ),
        transactions=transactions,
        pro_games=pro_games,
        pro_teams=pro_teams,
        warnings=warnings,
        lineups=parse_lineups(raw.get("daily_rosters") or {}),
        daily_totals=daily_lineup_totals(
            raw.get("daily_rosters") or {},
            players,
            season,
            # The previous matchup too, for its recap.
            (league.matchup_periods.get(league.matchup_period - 1) or [])
            + (league.matchup_periods.get(league.matchup_period) or []),
        ),
        pairings=parse_pairings(league_raw),
        demo=demo,
    )


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _team_id(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _find_key(data: Any, key: str) -> Any:
    """First value stored under `key` anywhere in a nested structure."""
    if isinstance(data, dict):
        if data.get(key) not in (None, "", []):
            return data[key]
        children = data.values()
    elif isinstance(data, list):
        children = data
    else:
        return None
    for child in children:
        found = _find_key(child, key)
        if found not in (None, "", []):
            return found
    return None


def _as_iso_date(value: Any) -> str | None:
    """ESPN dates come as [y, m, d, ...] lists, epoch ms or ISO strings."""
    if isinstance(value, list) and len(value) >= 3:
        try:
            return f"{int(value[0]):04d}-{int(value[1]):02d}-{int(value[2]):02d}"
        except (TypeError, ValueError):
            return None
    if isinstance(value, int | float):
        iso = ms_to_iso(value)
        return iso[:10] if iso else None
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


def line_from_stats(stats: dict[str, Any], averages: dict[str, Any] | None) -> StatLine:
    """An aggregate split: totals in `stats`, per-game values in `averageStats`."""
    gp = _num(stats.get(STAT_GP))
    line = StatLine(gp=gp, gs=_num(stats.get(STAT_GS)))
    for stat_id, name in STAT_FIELDS.items():
        if averages and stat_id in averages:
            value = _num(averages[stat_id])
        elif stat_id in stats:
            value = _num(stats[stat_id]) / gp if gp > 0 else _num(stats[stat_id])
        else:
            value = 0.0
        setattr(line, name, value)
    return line


def line_from_game(stats: dict[str, Any]) -> StatLine:
    line = StatLine(gp=1, gs=1.0 if _num(stats.get(STAT_GS)) > 0 else 0.0)
    for stat_id, name in STAT_FIELDS.items():
        setattr(line, name, _num(stats.get(stat_id)))
    return line


def parse_stat_entries(
    entries: list[dict[str, Any]], season: int
) -> tuple[dict[str, StatLine], list[Game]]:
    """Split ESPN's stats array into aggregate splits and single games.

    An aggregate's externalId is its season ("2027"); a single game's is the
    game id and it carries the scoring period it was played in.
    """
    splits: dict[str, StatLine] = {}
    games: dict[int, Game] = {}
    for entry in entries:
        stats = entry.get("stats") or {}
        source = entry.get("statSourceId")
        split = entry.get("statSplitTypeId")
        sp = int(entry.get("scoringPeriodId") or 0)
        season_id = entry.get("seasonId")
        aggregate = str(entry.get("externalId", "")) == str(season_id) or sp == 0
        if aggregate:
            if season_id == season:
                key = SPLIT_KEYS.get((source, split))
            elif season_id == season - 1 and (source, split) == (0, 0):
                key = "prev_season"
            else:
                key = None
            if key and stats:
                splits[key] = line_from_stats(stats, entry.get("averageStats"))
        elif source == 0 and season_id == season and stats:
            line = line_from_game(stats)
            if line.min > 0 or any(stats.values()):
                games[sp] = Game(sp=sp, team_id=int(entry.get("proTeamId") or 0), line=line)
    return splits, sorted(games.values(), key=lambda g: g.sp)


def merge_wrapper(
    players: dict[int, Player], wrapper: dict[str, Any], season: int
) -> Player | None:
    """Fold one player-pool entry ({id, status, onTeamId, ratings, player})
    into `players`."""
    data = wrapper.get("player") or {}
    player_id = data.get("id") or wrapper.get("id")
    if not player_id:
        return None
    player_id = int(player_id)
    player = players.get(player_id)
    if player is None:
        player = Player(id=player_id, name=data.get("fullName") or f"Player {player_id}")
        players[player_id] = player

    if data.get("fullName"):
        player.name = data["fullName"]
    if data.get("proTeamId") is not None:
        player.pro_team_id = int(data["proTeamId"])
    if data.get("defaultPositionId"):
        player.default_position = DEFAULT_POSITIONS.get(int(data["defaultPositionId"]), "")
    if data.get("eligibleSlots"):
        player.eligible_slots = [int(s) for s in data["eligibleSlots"]]
    if data.get("injuryStatus"):
        player.injury_status = data["injuryStatus"]
    expected = _as_iso_date(_find_key(data, "expectedReturnDate"))
    if expected:
        player.expected_return = expected

    ownership = data.get("ownership") or {}
    if "percentOwned" in ownership:
        player.percent_owned = _num(ownership.get("percentOwned"))
        player.percent_change = _num(ownership.get("percentChange"))
        player.percent_started = _num(ownership.get("percentStarted"))
    rank = ((data.get("draftRanksByRankType") or {}).get("STANDARD") or {}).get("rank")
    if rank:
        player.draft_rank = int(rank)

    for key, rating in (wrapper.get("ratings") or {}).items():
        name = RATING_KEYS.get(str(key))
        if name and isinstance(rating, dict):
            player.ratings[name] = Rating(
                rank=int(rating["totalRanking"]) if rating.get("totalRanking") else None,
                rating=_num(rating["totalRating"]) if "totalRating" in rating else None,
                pos_rank=(
                    int(rating["positionalRanking"]) if rating.get("positionalRanking") else None
                ),
            )

    # Rosters are parsed first and are authoritative for who owns whom; a
    # player card or pool list only fills these in when nothing has yet.
    if wrapper.get("status") and player.pool_status is None:
        player.pool_status = wrapper["status"]
    if _team_id(wrapper.get("onTeamId")) and player.on_team_id is None:
        player.on_team_id = _team_id(wrapper.get("onTeamId"))

    splits, games = parse_stat_entries(data.get("stats") or [], season)
    player.stats.update(splits)
    if games:
        by_sp = {g.sp: g for g in player.games}
        by_sp.update({g.sp: g for g in games})
        player.games = sorted(by_sp.values(), key=lambda g: g.sp)
    return player


def parse_league(raw: dict[str, Any], meta: dict[str, Any]) -> League:
    settings = raw.get("settings") or {}
    status = raw.get("status") or {}
    scoring = settings.get("scoringSettings") or {}
    roster_settings = settings.get("rosterSettings") or {}
    acquisitions = settings.get("acquisitionSettings") or {}
    schedule = settings.get("scheduleSettings") or {}

    names = [
        STAT_NAMES.get(str(item.get("statId")))
        for item in scoring.get("scoringItems") or []
        if STAT_NAMES.get(str(item.get("statId")))
    ]
    categories = [c for c in DEFAULT_CATEGORIES if c in names] + [
        c for c in names if c not in DEFAULT_CATEGORIES
    ]
    slots = {
        int(k): int(v) for k, v in (roster_settings.get("lineupSlotCounts") or {}).items() if v
    }
    limit = acquisitions.get("matchupAcquisitionLimit")
    return League(
        id=int(raw.get("id") or meta.get("league_id") or 0),
        season=int(raw.get("seasonId") or meta.get("season") or 0),
        name=settings.get("name") or "ESPN league",
        size=int(settings.get("size") or len(raw.get("teams") or [])),
        categories=categories or list(DEFAULT_CATEGORIES),
        lineup_slots=slots or dict(DEFAULT_LINEUP_SLOTS),
        scoring_period=int(raw.get("scoringPeriodId") or status.get("latestScoringPeriod") or 1),
        matchup_period=int(status.get("currentMatchupPeriod") or 1),
        matchup_periods={
            int(k): [int(x) for x in v] for k, v in (schedule.get("matchupPeriods") or {}).items()
        },
        first_scoring_period=int(status.get("firstScoringPeriod") or 1),
        final_scoring_period=int(status.get("finalScoringPeriod") or 0),
        matchup_acquisition_limit=int(limit) if limit and _num(limit) > 0 else None,
        waiver_hours=int(acquisitions["waiverHours"]) if acquisitions.get("waiverHours") else None,
        scoring_type=scoring.get("scoringType"),
        regular_periods=_int_or_none(schedule.get("matchupPeriodCount")),
        playoff_team_count=_int_or_none(schedule.get("playoffTeamCount")),
        divisions={
            int(d["id"]): d.get("name") or f"Division {d['id']}"
            for d in schedule.get("divisions") or []
            if d.get("id") is not None
        },
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def parse_pairings(raw: dict[str, Any]) -> dict[int, list[list[int]]]:
    """Every matchup of the season, by period: [[home id, away id], ...]."""
    pairings: dict[int, list[list[int]]] = {}
    for item in raw.get("schedule") or []:
        home = (item.get("home") or {}).get("teamId")
        away = (item.get("away") or {}).get("teamId")
        period = int(item.get("matchupPeriodId") or 0)
        if period and home and away:
            pairings.setdefault(period, []).append([int(home), int(away)])
    return pairings


def parse_pro_schedule(raw: Any) -> tuple[dict[int, str], list[ProGame]]:
    abbrevs: dict[int, str] = {}
    games: dict[int, ProGame] = {}
    for team in ((raw or {}).get("settings") or {}).get("proTeams") or []:
        team_id = int(team.get("id") or 0)
        if team_id == 0:
            continue
        abbrev = str(team.get("abbrev") or PRO_TEAMS.get(team_id, team_id)).upper()
        abbrevs[team_id] = ABBREV_FIXES.get(abbrev, abbrev)
        for sp_key, day_games in (team.get("proGamesByScoringPeriod") or {}).items():
            for game in day_games or []:
                start = ms_to_iso(game.get("date"))
                if not game.get("id") or not start or int(game["id"]) in games:
                    continue
                games[int(game["id"])] = ProGame(
                    id=int(game["id"]),
                    sp=int(game.get("scoringPeriodId") or sp_key),
                    start=start,
                    date=eastern_date(start).isoformat(),
                    home_id=int(game.get("homeProTeamId") or 0),
                    away_id=int(game.get("awayProTeamId") or 0),
                )
    return abbrevs, sorted(games.values(), key=lambda g: (g.start, g.id))


def parse_teams(raw: dict[str, Any], players: dict[int, Player], season: int) -> list[Team]:
    members = {
        m.get("id"): m.get("displayName")
        or " ".join(x for x in (m.get("firstName"), m.get("lastName")) if x)
        for m in raw.get("members") or []
    }
    teams = []
    for data in raw.get("teams") or []:
        team_id = int(data["id"])
        name = (
            data.get("name")
            or f"{data.get('location', '')} {data.get('nickname', '')}".strip()
            or data.get("abbrev")
            or f"Team {team_id}"
        )
        record = (data.get("record") or {}).get("overall") or {}
        counter = data.get("transactionCounter") or {}
        team = Team(
            id=team_id,
            name=name,
            abbrev=data.get("abbrev") or "",
            owners=[members[o] for o in data.get("owners") or [] if members.get(o)],
            wins=int(record.get("wins") or 0),
            losses=int(record.get("losses") or 0),
            ties=int(record.get("ties") or 0),
            waiver_rank=int(data["waiverRank"]) if data.get("waiverRank") else None,
            acquisitions_total=(
                int(counter["acquisitions"]) if counter.get("acquisitions") is not None else None
            ),
            matchup_acquisitions={
                int(k): int(v) for k, v in (counter.get("matchupAcquisitionTotals") or {}).items()
            },
            season_stats=_season_stats(data.get("valuesByStat") or {}),
            division_id=int(data["divisionId"]) if data.get("divisionId") is not None else None,
            playoff_seed=_int_or_none(data.get("playoffSeed")) or None,
        )
        for entry in (data.get("roster") or {}).get("entries") or []:
            wrapper = dict(entry.get("playerPoolEntry") or {})
            wrapper.setdefault("id", entry.get("playerId"))
            player = merge_wrapper(players, wrapper, season)
            if player is None:
                continue
            player.pool_status = "ONTEAM"
            player.on_team_id = team_id
            if not (wrapper.get("player") or {}).get("injuryStatus") and entry.get("injuryStatus"):
                player.injury_status = entry["injuryStatus"]
            team.roster.append(
                RosterSpot(
                    player_id=player.id,
                    slot_id=int(entry.get("lineupSlotId", 12)),
                    acquisition_type=entry.get("acquisitionType"),
                    acquisition_date=ms_to_iso(entry.get("acquisitionDate")),
                )
            )
        teams.append(team)
    return sorted(teams, key=lambda t: t.id)


def _season_stats(values: dict[str, Any]) -> dict[str, float]:
    """A team's season-to-date totals (ESPN's valuesByStat), by stat name."""
    stats = {}
    for stat_id, value in values.items():
        name = STAT_NAMES.get(str(stat_id))
        if name and value is not None:
            number = _num(value)
            stats[name] = number / 100 if name in PERCENT_STATS and number > 1 else number
    return stats


def _matchup_side(data: dict[str, Any]) -> MatchupSide:
    cumulative = data.get("cumulativeScore") or {}
    stats: dict[str, float] = {}
    results: dict[str, str] = {}
    for stat_id, item in (cumulative.get("scoreByStat") or {}).items():
        name = STAT_NAMES.get(str(stat_id))
        if not name or not isinstance(item, dict):
            continue
        if item.get("score") is not None:
            value = _num(item["score"])
            stats[name] = value / 100 if name in PERCENT_STATS and value > 1 else value
        if item.get("result"):
            results[name] = item["result"]
    return MatchupSide(
        team_id=int(data.get("teamId") or 0),
        stats=stats,
        results=results,
        wins=int(cumulative.get("wins") or 0),
        losses=int(cumulative.get("losses") or 0),
        ties=int(cumulative.get("ties") or 0),
    )


def parse_matchups(raw: dict[str, Any], period: int, around: int = 0) -> list[Matchup]:
    """Matchups of `period`, and with `around` the periods either side of it
    (last week's final results, next week's opponents)."""
    wanted = range(period - around, period + around + 1)
    matchups = []
    for item in raw.get("schedule") or []:
        item_period = int(item.get("matchupPeriodId") or 0)
        if item_period not in wanted or not item.get("home"):
            continue
        matchups.append(
            Matchup(
                period=item_period,
                home=_matchup_side(item["home"]),
                away=_matchup_side(item["away"]) if item.get("away") else None,
                winner=item.get("winner") or "UNDECIDED",
            )
        )
    return matchups


def merge_live_scores(matchups: list[Matchup], live: list[Matchup]) -> list[Matchup]:
    """The scoreboard's current-week scores replace the league response's."""
    by_pair = {(m.period, m.home.team_id): m for m in live}
    return [by_pair.get((m.period, m.home.team_id), m) for m in matchups]


TOTAL_FIELDS = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TO": "to",
    "3PM": "tpm",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
}


def parse_lineups(daily: dict[str, Any]) -> dict[int, dict[int, dict[int, int]]]:
    lineups: dict[int, dict[int, dict[int, int]]] = {}
    for key, response in daily.items():
        for team in (response or {}).get("teams") or []:
            slots = {
                int(e["playerId"]): int(e.get("lineupSlotId", BENCH_SLOT))
                for e in (team.get("roster") or {}).get("entries") or []
                if e.get("playerId")
            }
            if slots:
                lineups.setdefault(int(key), {})[int(team.get("id") or 0)] = slots
    return lineups


def lineup_totals(
    daily: dict[str, Any], players: dict[int, Player], season: int, sps: list[int]
) -> dict[int, dict[str, float]]:
    """Each team's category totals so far this matchup, from the lineup it
    had each day (players in starting slots) and their box scores."""
    totals: dict[int, dict[str, float]] = {}
    for by_team in daily_lineup_totals(daily, players, season, sps).values():
        for team_id, day in by_team.items():
            sums = totals.setdefault(team_id, dict.fromkeys(day, 0.0))
            for name, value in day.items():
                sums[name] += value
    return totals


def daily_lineup_totals(
    daily: dict[str, Any], players: dict[int, Player], season: int, sps: list[int]
) -> dict[int, dict[int, dict[str, float]]]:
    """Scoring period -> team id -> that day's totals of its starters (GP too)."""
    out: dict[int, dict[int, dict[str, float]]] = {}
    wanted = set(sps)
    for key, response in daily.items():
        sp = int(key)
        if sp not in wanted:
            continue
        for team in (response or {}).get("teams") or []:
            team_id = int(team.get("id") or 0)
            day = out.setdefault(sp, {})
            sums = day.setdefault(team_id, dict.fromkeys(TOTAL_FIELDS, 0.0) | {"GP": 0.0})
            for entry in (team.get("roster") or {}).get("entries") or []:
                if int(entry.get("lineupSlotId", BENCH_SLOT)) in NON_STARTING_SLOTS:
                    continue
                game = _game_on(entry, players, season, sp)
                if game is None or not game.played:
                    continue
                sums["GP"] += 1
                for name, attr in TOTAL_FIELDS.items():
                    sums[name] += getattr(game.line, attr)
    return out


def _game_on(
    entry: dict[str, Any], players: dict[int, Player], season: int, sp: int
) -> Game | None:
    player = players.get(int(entry.get("playerId") or 0))
    if player is not None:
        game = next((g for g in player.games if g.sp == sp), None)
        if game is not None:
            return game
    stats = ((entry.get("playerPoolEntry") or {}).get("player") or {}).get("stats") or []
    _, games = parse_stat_entries(stats, season)
    return next((g for g in games if g.sp == sp), None)


def apply_lineup_totals(
    matchups: list[Matchup], totals: dict[int, dict[str, float]], league: League
) -> list[Matchup]:
    """Use the lineup totals for the current matchup when ESPN's own are
    behind (fewer points than the box scores add up to)."""
    for matchup in matchups:
        if matchup.period != league.matchup_period or matchup.away is None:
            continue
        sides = (matchup.home, matchup.away)
        mine = [totals.get(side.team_id) for side in sides]
        if any(t is None for t in mine):
            continue
        espn_points = max(side.stats.get("PTS", 0.0) for side in sides)
        live_points = max(t["PTS"] for t in mine)  # type: ignore[index]
        if live_points <= espn_points:
            continue
        for side, sums in zip(sides, mine, strict=True):
            stats = {k: v for k, v in sums.items() if k != "GP"}  # type: ignore[union-attr]
            stats["FG%"] = stats["FGM"] / stats["FGA"] if stats["FGA"] else 0.0
            stats["FT%"] = stats["FTM"] / stats["FTA"] if stats["FTA"] else 0.0
            side.stats = stats
        _score(matchup.home, matchup.away, league.categories)
    return matchups


def _score(home: MatchupSide, away: MatchupSide, categories: list[str]) -> None:
    home.wins = home.losses = home.ties = 0
    away.wins = away.losses = away.ties = 0
    home.results, away.results = {}, {}
    for cat in categories:
        a, b = home.stats.get(cat), away.stats.get(cat)
        if a is None or b is None:
            continue
        if cat == "TO":
            a, b = -a, -b
        if a > b:
            home.results[cat], away.results[cat] = "WIN", "LOSS"
            home.wins += 1
            away.losses += 1
        elif a < b:
            home.results[cat], away.results[cat] = "LOSS", "WIN"
            home.losses += 1
            away.wins += 1
        else:
            home.results[cat] = away.results[cat] = "TIE"
            home.ties += 1
            away.ties += 1


def parse_transactions(responses: list[Any]) -> list[Transaction]:
    found: dict[str, Transaction] = {}
    for response in responses:
        for data in (response or {}).get("transactions") or []:
            kind = data.get("type")
            if kind not in TRANSACTION_TYPES or data.get("status") in ("CANCELED", "PENDING"):
                continue
            items = [
                TransactionItem(
                    type=item["type"],
                    player_id=int(item["playerId"]),
                    from_team_id=_team_id(item.get("fromTeamId")),
                    to_team_id=_team_id(item.get("toTeamId")),
                )
                for item in data.get("items") or []
                if item.get("type") in KEPT_ITEM_TYPES and item.get("playerId")
            ]
            ts = ms_to_iso(
                data.get("processDate") or data.get("acceptedDate") or data.get("proposedDate")
            )
            transaction_id = str(data.get("id") or f"{kind}-{data.get('teamId')}-{ts}-{len(found)}")
            found[transaction_id] = Transaction(
                id=transaction_id,
                type=kind,
                status=data.get("status") or "",
                ts=ts,
                sp=int(data["scoringPeriodId"]) if data.get("scoringPeriodId") else None,
                team_id=_team_id(data.get("teamId")),
                bid=_num(data["bidAmount"]) if data.get("bidAmount") else None,
                items=items,
            )
    return sorted(found.values(), key=lambda t: t.ts or "", reverse=True)


def add_index_players(
    players: dict[int, Player], index: Any, transactions: list[Transaction]
) -> None:
    """Names for players that only appear in transactions (dropped and gone)."""
    needed = {i.player_id for t in transactions for i in t.items} - players.keys()
    if not needed:
        return
    rows = index.get("players", []) if isinstance(index, dict) else index or []
    for row in rows:
        player_id = int(row.get("id") or 0)
        if player_id in needed:
            players[player_id] = Player(
                id=player_id,
                name=row.get("fullName") or f"Player {player_id}",
                pro_team_id=int(row.get("proTeamId") or 0),
                default_position=DEFAULT_POSITIONS.get(int(row.get("defaultPositionId") or 0), ""),
                eligible_slots=[int(s) for s in row.get("eligibleSlots") or []],
            )


def normalise_name(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", plain)
    return re.sub(r"[^a-z]", "", plain)


def _athlete_id(athlete: dict[str, Any]) -> int | None:
    if str(athlete.get("id", "")).isdigit():
        return int(athlete["id"])
    match = re.search(r"~a:(\d+)", str(athlete.get("uid", "")))
    if match:
        return int(match.group(1))
    for link in athlete.get("links") or []:
        match = re.search(r"/id/(\d+)", str(link.get("href", "")))
        if match:
            return int(match.group(1))
    return None


def apply_injury_notes(players: dict[int, Player], raw: Any) -> None:
    """Attach ESPN's NBA injury report (description, date, return estimate).

    ESPN athlete ids are the same ids the fantasy game uses; names are the
    fallback when an entry carries no id.
    """
    by_id: dict[int, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for team in (raw or {}).get("injuries") or []:
        for injury in team.get("injuries") or []:
            athlete = injury.get("athlete") or {}
            details = injury.get("details") or {}
            side = details.get("side")
            description = " ".join(
                str(x)
                for x in (
                    side if side and side != "Not Specified" else None,
                    details.get("type"),
                    details.get("detail"),
                )
                if x
            )
            comment = injury.get("shortComment") or injury.get("longComment")
            entry = {
                "note": f"{description}: {comment}"
                if description and comment
                else description or comment,
                "date": str(injury.get("date") or "")[:10] or None,
                "return": _as_iso_date(details.get("returnDate")),
            }
            athlete_id = _athlete_id(athlete)
            if athlete_id:
                by_id[athlete_id] = entry
            if athlete.get("displayName"):
                by_name[normalise_name(athlete["displayName"])] = entry

    for player in players.values():
        entry = by_id.get(player.id) or by_name.get(normalise_name(player.name))
        if not entry:
            continue
        player.injury_note = entry["note"] or player.injury_note
        player.injury_date = entry["date"] or player.injury_date
        if not player.expected_return and entry["return"]:
            player.expected_return = entry["return"]


def estimate_waiver_clear(
    players: dict[int, Player],
    free_agent_ids: list[int],
    transactions: list[Transaction],
    waiver_hours: int | None,
) -> None:
    """ESPN doesn't say when a waived player clears; the drop time plus the
    league's waiver period is the estimate."""
    last_drop: dict[int, str] = {}
    for transaction in transactions:
        for item in transaction.items:
            if item.type == "DROP" and transaction.ts:
                last_drop[item.player_id] = max(last_drop.get(item.player_id, ""), transaction.ts)
    for player_id in free_agent_ids:
        player = players[player_id]
        if player.pool_status != "WAIVERS" or player.waiver_clear:
            continue
        if player_id in last_drop:
            cleared = parse_iso(last_drop[player_id]) + timedelta(hours=waiver_hours or 24)
            player.waiver_clear = cleared.isoformat()
            player.waiver_clear_estimated = True


def find_team(teams: list[Team], hint: str | None) -> int | None:
    if not hint:
        return None
    wanted = " ".join(hint.split()).casefold()
    if wanted.isdigit():
        return next((t.id for t in teams if t.id == int(wanted)), None)
    for attribute in ("name", "abbrev"):
        for team in teams:
            if " ".join(getattr(team, attribute).split()).casefold() == wanted:
                return team.id
    partial = [t.id for t in teams if wanted in t.name.casefold()]
    return partial[0] if len(partial) == 1 else None


MAX_WEEKS_PER_MATCHUP = 3


def matchup_scoring_periods(
    periods: dict[int, list[int]], sp_dates: dict[int, date], first: int, final: int
) -> dict[int, list[int]]:
    """Matchup period -> its scoring periods (days).

    ESPN's matchupPeriods lists the weeks each matchup covers: one, or two
    or three around the All-Star break and in the playoffs. A week runs
    Monday to Sunday, the first from the season's first scoring period to
    the first Sunday. Lists that are already days are kept as they are.
    """
    if not periods or not sp_dates:
        return periods
    if max(len(v) for v in periods.values()) > MAX_WEEKS_PER_MATCHUP:
        return periods
    last = final or max(sp_dates)
    weeks: dict[int, list[int]] = {}
    week = 1
    for sp in range(first, last + 1):
        day = date_for_sp(sp_dates, sp)
        if day is None:
            continue
        if sp > first and day.weekday() == 0:
            week += 1
        weeks.setdefault(week, []).append(sp)
    return {
        period: sorted(sp for w in ids for sp in weeks.get(w, []))
        for period, ids in periods.items()
    }
