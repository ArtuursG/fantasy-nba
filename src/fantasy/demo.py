"""An invented league in ESPN's response format.

`DemoWorld(now).bundle(as_of)` returns the same raw responses
`espn.client.fetch_bundle` would, for any moment, so the demo and the tests
run the real parser and analysis. Players and stats are made up; the world
is seeded, and a player's game on a given day is the same in every bundle,
so snapshots taken "yesterday" and "today" differ only where time moved on.

Planted storylines, so every report section has something to show: a
starter of mine back from injury and ramping up, a teammate of mine turning
day-to-day today, an injured player in my IR slot, the opponent's best
player ruled out today, an injured starter whose backup (a free agent) has
taken his minutes, a likely rookie earning minutes, an add-rate surge, a
starter who lost his job, and transactions including one by my opponent
since yesterday.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from fantasy.config import default_season
from fantasy.espn.constants import PRO_TEAMS
from fantasy.timeutil import EASTERN

DEMO_LEAGUE_ID = 424242
LEAGUE_NAME = "Demo League"
MY_TEAM = "Home Team"
TEAM_NAMES = [
    MY_TEAM,
    "Sabiles Stealers",
    "Bullu Kojas",
    "Kurzemes Kanoni",
    "Daugavas Dunks",
    "Latgales Lusi",
    "Rigas Raketes",
    "Vidzemes Vilki",
    "Zemgales Zibens",
    "Jurmalas Vilni",
]
FIRST = (
    "Aaron Andre Ben Caleb Chris Dante Darius Devin Eli Evan Felix Gabe Hugo Isaac Jalen Jamal "
    "Jaylen Jonah Kai Kobe Leo Malik Marcus Miles Nate Noah Omar Owen Quinn Ray Reggie Sam "
    "Terrence Theo Tyler Victor Wes Xavier Zach Zion"
).split()
LAST = (
    "Abbott Alvarez Baker Banks Bishop Boone Brooks Carter Coleman Dawson Ellis Fisher Fleming "
    "Foster Garner Graves Hale Harper Hayes Holt Ingram Jensen Keller Lambert Lowe Mack Mercer "
    "Monroe Nash Norris Owens Parks Pierce Porter Quinn Reed Rhodes Rowe Sawyer Shaw Sloan "
    "Stone Sutton Tate Turner Vaughn Wade Walsh Ward Webb Wells Wilder York Young Zeller"
).split()

ARCHETYPES: dict[str, dict[str, Any]] = {
    "PG": {
        "slots": [0, 5, 11, 12, 13],
        "default": 1,
        "rates": {"pts": 20, "reb": 4.5, "ast": 8, "stl": 1.4, "blk": 0.3, "tpm": 2.6, "to": 3.0},
        "fga": 16.0,
        "fta": 4.5,
        "fg": 0.45,
        "ft": 0.86,
    },
    "G": {
        "slots": [0, 1, 5, 11, 12, 13],
        "default": 2,
        "rates": {"pts": 21, "reb": 4.0, "ast": 5.5, "stl": 1.3, "blk": 0.3, "tpm": 3.0, "to": 2.6},
        "fga": 17.0,
        "fta": 4.0,
        "fg": 0.45,
        "ft": 0.85,
    },
    "W": {
        "slots": [1, 2, 5, 6, 7, 8, 11, 12, 13],
        "default": 3,
        "rates": {"pts": 18, "reb": 5.5, "ast": 3.5, "stl": 1.3, "blk": 0.5, "tpm": 2.8, "to": 2.0},
        "fga": 14.5,
        "fta": 3.5,
        "fg": 0.46,
        "ft": 0.82,
    },
    "F": {
        "slots": [2, 3, 6, 8, 11, 12, 13],
        "default": 3,
        "rates": {"pts": 17, "reb": 8.0, "ast": 3.0, "stl": 1.0, "blk": 0.9, "tpm": 1.6, "to": 1.8},
        "fga": 13.0,
        "fta": 3.5,
        "fg": 0.48,
        "ft": 0.77,
    },
    "B": {
        "slots": [3, 4, 6, 9, 10, 11, 12, 13],
        "default": 4,
        "rates": {
            "pts": 16,
            "reb": 10.5,
            "ast": 2.5,
            "stl": 0.8,
            "blk": 1.6,
            "tpm": 0.9,
            "to": 1.9,
        },
        "fga": 12.0,
        "fta": 4.0,
        "fg": 0.53,
        "ft": 0.72,
    },
    "C": {
        "slots": [4, 11, 12, 13],
        "default": 5,
        "rates": {
            "pts": 15,
            "reb": 12.5,
            "ast": 2.3,
            "stl": 0.7,
            "blk": 2.1,
            "tpm": 0.3,
            "to": 2.0,
        },
        "fga": 11.0,
        "fta": 4.5,
        "fg": 0.58,
        "ft": 0.66,
    },
}
ROSTER_SHAPE = ["PG", "G", "W", "W", "F", "F", "B", "C", "PG", "W", "F", "B", "C"]
DAILY_GAMES = {0: 8, 1: 6, 2: 11, 3: 4, 4: 9, 5: 7, 6: 10}  # Monday = 0
TIPOFF = time(19, 30)
WEEKS_PLAYED = 4
WEEKS_SCHEDULED = 6
STAT_IDS = {
    "pts": "0",
    "blk": "1",
    "stl": "2",
    "ast": "3",
    "reb": "6",
    "to": "11",
    "fgm": "13",
    "fga": "14",
    "ftm": "15",
    "fta": "16",
    "tpm": "17",
    "tpa": "18",
    "oreb": "4",
    "dreb": "5",
    "min": "40",
    "gs": "41",
    "gp": "42",
}
CATEGORY_IDS = ["19", "20", "17", "6", "3", "2", "1", "11", "0"]


@dataclass
class DemoPlayer:
    id: int
    name: str
    pro_team: int
    arch: str
    quality: float
    base_min: float
    starter: bool
    rookie: bool = False
    statuses: list[tuple[int, str]] = field(default_factory=list)
    note: str | None = None
    injury: tuple[str, str, str] | None = None
    return_offset: int | None = None
    shift: tuple[int, float, bool] | None = None
    min_override: dict[int, float] = field(default_factory=dict)
    owned: float = 50.0
    change: float = 0.0

    def status(self, sp: int) -> str:
        current = "ACTIVE"
        for start, status in sorted(self.statuses):
            if sp >= start:
                current = status
        return current

    def minutes(self, sp: int) -> tuple[float, bool]:
        base, starter = self.base_min, self.starter
        if self.shift and sp >= self.shift[0]:
            base, starter = self.shift[1], self.shift[2]
        return self.min_override.get(sp, base), starter


@dataclass
class DemoGame:
    id: int
    sp: int
    start: datetime
    home: int
    away: int


@dataclass
class Event:
    ts: datetime
    sp: int
    team: int
    kind: str
    status: str
    added: int | None
    dropped: int | None


class DemoWorld:
    def __init__(self, now: datetime | None = None, seed: int = 7) -> None:
        self.now = now or datetime.now(UTC)
        self.rng = random.Random(seed)
        today = self.now.astimezone(EASTERN).date()
        monday = today - timedelta(days=today.weekday())
        self.start = monday - timedelta(weeks=WEEKS_PLAYED)
        self.season = default_season(today)
        self.today_sp = self.sp_of(today)
        self.games = self._schedule()
        self._games_by_sp: dict[int, list[DemoGame]] = {}
        for game in self.games:
            self._games_by_sp.setdefault(game.sp, []).append(game)
        self._stats_cache: dict[tuple[int, int], dict[str, float] | None] = {}
        self.players: dict[int, DemoPlayer] = {}
        self._games_cache: dict[tuple[int, datetime], list[tuple[DemoGame, dict]]] = {}
        self.rosters: dict[int, list[int]] = {}
        self.ir: dict[int, int] = {}
        self.free_agents: list[int] = []
        self._build_players()
        self._plant_storylines()
        self.events = self._events()

    def sp_of(self, day: date) -> int:
        return (day - self.start).days + 1

    def date_of(self, sp: int) -> date:
        return self.start + timedelta(days=sp - 1)

    def _schedule(self) -> list[DemoGame]:
        """Random pairings, but like the NBA: nobody plays three days running,
        and teams that rested yesterday are likelier to play today."""
        games: list[DemoGame] = []
        played: dict[int, set[int]] = {team: set() for team in range(1, 31)}
        for sp in range(1, WEEKS_SCHEDULED * 7 + 1):
            day = self.date_of(sp)
            eligible = [t for t in played if not {sp - 1, sp - 2} <= played[t]]
            count = max(2, DAILY_GAMES[day.weekday()] + self.rng.choice([-1, 0, 0, 1]))
            count = min(count, len(eligible) // 2)
            teams: list[int] = []
            while len(teams) < count * 2:
                pool = [t for t in eligible if t not in teams]
                weights = [1.0 if sp - 1 in played[t] else 3.0 for t in pool]
                teams.append(self.rng.choices(pool, weights)[0])
            start = datetime.combine(day, TIPOFF, EASTERN).astimezone(UTC)
            for i in range(count):
                home, away = teams[2 * i], teams[2 * i + 1]
                played[home].add(sp)
                played[away].add(sp)
                games.append(
                    DemoGame(
                        id=401_800_000 + len(games),
                        sp=sp,
                        start=start + timedelta(minutes=30 * (i % 3)),
                        home=home,
                        away=away,
                    )
                )
        return games

    def _new_player(self, arch: str, quality: float, base_min: float, starter: bool) -> DemoPlayer:
        player_id = 4_000_000 + len(self.players) * 37
        while True:
            name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
            if all(p.name != name for p in self.players.values()):
                break
        player = DemoPlayer(
            id=player_id,
            name=name,
            pro_team=self.rng.randint(1, 30),
            arch=arch,
            quality=quality,
            base_min=base_min,
            starter=starter,
        )
        self.players[player_id] = player
        return player

    def _build_players(self) -> None:
        for team_id in range(1, len(TEAM_NAMES) + 1):
            ids = []
            for i, arch in enumerate(ROSTER_SHAPE):
                core = i < 8
                player = self._new_player(
                    arch,
                    quality=self.rng.uniform(0.95, 1.3) if core else self.rng.uniform(0.8, 1.05),
                    base_min=self.rng.uniform(30, 36) if core else self.rng.uniform(22, 30),
                    starter=core or self.rng.random() < 0.3,
                )
                player.owned = self.rng.uniform(85, 100) if core else self.rng.uniform(45, 85)
                player.change = self.rng.uniform(-1.5, 1.5)
                ids.append(player.id)
            self.rosters[team_id] = ids
        for _ in range(70):
            player = self._new_player(
                self.rng.choice(list(ARCHETYPES)),
                quality=self.rng.uniform(0.6, 1.0),
                base_min=self.rng.uniform(12, 27),
                starter=self.rng.random() < 0.2,
            )
            player.owned = self.rng.uniform(0.5, 40)
            player.change = self.rng.uniform(-3, 3)
            self.free_agents.append(player.id)

    def _player(self, team_id: int, index: int) -> DemoPlayer:
        return self.players[self.rosters[team_id][index]]

    def _plant_storylines(self) -> None:
        t = self.today_sp
        returner = self._player(1, 1)
        returner.statuses = [(t - 12, "OUT"), (t - 3, "ACTIVE")]
        returner.min_override = {sp: returner.base_min * 0.68 for sp in range(t - 3, t)}

        dtd = self._player(1, 4)
        dtd.statuses = [(t, "DAY_TO_DAY")]
        dtd.note = "Questionable with left ankle soreness."
        dtd.injury = ("Left", "Ankle", "Soreness")

        ir_player = self._new_player("F", 1.1, 31, True)
        ir_player.statuses = [(t - 20, "OUT")]
        ir_player.note = "Out at least another week with a right knee sprain."
        ir_player.injury = ("Right", "Knee", "Sprain")
        ir_player.return_offset = 9
        ir_player.owned = 72.0
        self.ir[1] = ir_player.id

        star = max((self._player(2, i) for i in range(8)), key=lambda p: p.quality)
        star.statuses = [(t, "OUT")]
        star.note = "Ruled out with a hamstring strain; re-evaluated in a few days."
        star.injury = ("Left", "Hamstring", "Strain")
        star.return_offset = 4

        injured = self._player(5, 2)
        injured.arch, injured.base_min, injured.quality = "W", 33.0, 1.15
        injured.statuses = [(t - 9, "OUT")]
        injured.note = "Out with a fractured left hand."
        injured.injury = ("Left", "Hand", "Fracture")
        injured.return_offset = 14
        backup = self.players[self.free_agents[0]]
        backup.arch, backup.pro_team, backup.quality = "W", injured.pro_team, 0.95
        backup.base_min, backup.starter = 17.0, False
        backup.shift = (t - 9, 31.0, True)
        backup.owned, backup.change = 21.0, 9.5

        rookie = self.players[self.free_agents[1]]
        rookie.rookie, rookie.arch, rookie.quality = True, "B", 0.9
        rookie.base_min, rookie.starter = 14.0, False
        rookie.shift = (t - 6, 27.0, False)
        rookie.owned, rookie.change = 9.0, 6.2

        surge = self.players[self.free_agents[2]]
        surge.quality, surge.base_min = 0.97, 26.0
        surge.owned, surge.change = 38.0, 16.0

        benched = self._player(6, 3)
        benched.starter, benched.base_min = True, 31.0
        benched.shift = (t - 10, 21.0, False)

        # A bench player of mine whose team plays tonight: the lineup check
        # should tell me to start him.
        tonight = next(g for g in self.games if g.sp == t)
        idle_bench = min(
            (self._player(1, i) for i in range(8, len(ROSTER_SHAPE))),
            key=lambda p: p.quality * p.base_min,
        )
        idle_bench.pro_team = tonight.home

        # Give my roster exactly three C-eligible players, under the cap of 4.
        my_team = [self.players[p] for p in self.rosters[1]]
        for player in my_team:
            if player.arch == "B" and player is not my_team[6]:
                player.arch = "F"

    def _events(self) -> list[Event]:
        """Adds and drops over the last 9 days. Rosters above are the state
        *after* them; a bundle for an earlier moment undoes later events."""
        events = []
        used = {self.free_agents[0], self.free_agents[1], self.free_agents[2]}
        plan = [
            (8.6, 4, "FREEAGENT"),
            (6.2, 7, "WAIVER"),
            (5.1, 9, "FREEAGENT"),
            (3.4, 1, "FREEAGENT"),
            (2.5, 3, "FREEAGENT"),
            (1.6, 8, "WAIVER"),
            (0.4, 2, "FREEAGENT"),
        ]
        bench_slots = list(range(8, len(ROSTER_SHAPE)))
        for days_ago, team_id, kind in plan:
            ts = self.now - timedelta(days=days_ago)
            added = self.rosters[team_id][self.rng.choice(bench_slots)]
            while added in used:
                added = self.rosters[team_id][self.rng.choice(bench_slots)]
            dropped = self._new_player(
                self.rng.choice(list(ARCHETYPES)), self.rng.uniform(0.55, 0.85), 15.0, False
            )
            dropped.owned, dropped.change = self.rng.uniform(5, 30), -self.rng.uniform(2, 8)
            self.free_agents.append(dropped.id)
            used |= {added, dropped.id}
            sp = self.sp_of(ts.astimezone(EASTERN).date())
            events.append(Event(ts, sp, team_id, kind, "EXECUTED", added, dropped.id))
        failed_ts = self.now - timedelta(days=1.6)
        events.append(
            Event(
                failed_ts,
                self.sp_of(failed_ts.astimezone(EASTERN).date()),
                5,
                "WAIVER_ERROR",
                "FAILED_PLAYERALREADYDROPPED",
                events[5].added,
                None,
            )
        )
        return events

    # -- state at a moment ------------------------------------------------

    def _rosters_at(self, as_of: datetime) -> tuple[dict[int, list[int]], list[int]]:
        rosters = {team: list(ids) for team, ids in self.rosters.items()}
        free = list(self.free_agents)
        for event in sorted(self.events, key=lambda e: e.ts, reverse=True):
            if event.ts <= as_of or event.status != "EXECUTED":
                continue
            assert event.added is not None and event.dropped is not None
            team = rosters[event.team]
            team[team.index(event.added)] = event.dropped
            free.remove(event.dropped)
            free.append(event.added)
        return rosters, free

    def _game_stats(self, player: DemoPlayer, game: DemoGame) -> dict[str, float] | None:
        key = (player.id, game.id)
        if key not in self._stats_cache:
            self._stats_cache[key] = self._draw_game(player, game)
        return self._stats_cache[key]

    def _draw_game(self, player: DemoPlayer, game: DemoGame) -> dict[str, float] | None:
        if player.status(game.sp) in ("OUT", "SUSPENSION"):
            return None
        rng = random.Random(player.id * 1009 + game.sp)
        minutes, starter = player.minutes(game.sp)
        minutes = max(4.0, min(42.0, rng.gauss(minutes, 3.5)))
        arch = ARCHETYPES[player.arch]
        scale = minutes / 36 * player.quality

        def draw(mean: float) -> int:
            return max(0, round(rng.gauss(mean, math.sqrt(max(mean, 0.05)) * 1.1)))

        fga = draw(arch["fga"] * scale)
        fgm = sum(1 for _ in range(fga) if rng.random() < arch["fg"])
        fta = draw(arch["fta"] * scale)
        ftm = sum(1 for _ in range(fta) if rng.random() < arch["ft"])
        tpm = min(draw(arch["rates"]["tpm"] * scale), fgm)
        line = {
            "min": round(minutes),
            "fgm": fgm,
            "fga": fga,
            "ftm": ftm,
            "fta": fta,
            "tpm": tpm,
            "pts": 2 * fgm + tpm + ftm,
            "gs": 1 if starter else 0,
            "gp": 1,
        }
        for stat in ("reb", "ast", "stl", "blk", "to"):
            line[stat] = draw(arch["rates"][stat] * scale)
        line["tpa"] = tpm + draw(arch["rates"]["tpm"] * scale * 1.7)
        offensive_share = 0.3 if player.arch in ("B", "C") else 0.2
        line["oreb"] = sum(1 for _ in range(line["reb"]) if rng.random() < offensive_share)
        line["dreb"] = line["reb"] - line["oreb"]
        return line

    def _player_games(self, player: DemoPlayer, as_of: datetime) -> list[tuple[DemoGame, dict]]:
        key = (player.id, as_of)
        if key in self._games_cache:
            return self._games_cache[key]
        out = []
        for game in self.games:
            if player.pro_team not in (game.home, game.away):
                continue
            if game.start + timedelta(hours=3) > as_of:
                continue
            stats = self._game_stats(player, game)
            if stats:
                out.append((game, stats))
        self._games_cache[key] = out
        return out

    @staticmethod
    def _aggregate(lines: list[dict]) -> tuple[dict, dict]:
        totals: dict[str, float] = {}
        for line in lines:
            for key, value in line.items():
                totals[key] = totals.get(key, 0) + value
        gp = len(lines)
        stats = {STAT_IDS[k]: v for k, v in totals.items()}
        stats[STAT_IDS["gp"]] = gp
        averages = {STAT_IDS[k]: v / gp for k, v in totals.items() if k not in ("gp", "gs")}
        return stats, averages

    def _projection(self, player: DemoPlayer, gp: int, noise: float) -> tuple[dict, dict]:
        arch = ARCHETYPES[player.arch]
        rng = random.Random(player.id + int(noise * 1000))
        scale = player.base_min / 36 * player.quality * rng.uniform(1 - noise, 1 + noise)
        avg = {k: v * scale for k, v in arch["rates"].items()}
        avg["fga"], avg["fta"] = arch["fga"] * scale, arch["fta"] * scale
        avg["fgm"], avg["ftm"] = avg["fga"] * arch["fg"], avg["fta"] * arch["ft"]
        avg["tpm"] = min(avg["tpm"], avg["fgm"])
        avg["tpa"] = avg["tpm"] * 2.7
        avg["oreb"] = avg["reb"] * (0.3 if player.arch in ("B", "C") else 0.2)
        avg["dreb"] = avg["reb"] - avg["oreb"]
        avg["pts"] = 2 * avg["fgm"] + avg["tpm"] + avg["ftm"]
        avg["min"] = player.base_min
        averages = {STAT_IDS[k]: v for k, v in avg.items()}
        stats = {k: v * gp for k, v in averages.items()}
        stats[STAT_IDS["gp"]] = gp
        stats[STAT_IDS["gs"]] = gp if player.starter else 0
        return stats, averages

    def _stats_entries(self, player: DemoPlayer, as_of: datetime, game_logs: bool) -> list[dict]:
        games = self._player_games(player, as_of)
        today = as_of.astimezone(EASTERN).date()
        entries = []

        def aggregate(split: int, lines: list[dict]) -> None:
            if not lines:
                return
            stats, averages = self._aggregate(lines)
            entries.append(
                {
                    "id": f"0{split}{self.season}",
                    "externalId": str(self.season),
                    "seasonId": self.season,
                    "scoringPeriodId": 0,
                    "statSourceId": 0,
                    "statSplitTypeId": split,
                    "stats": stats,
                    "averageStats": averages,
                }
            )

        aggregate(0, [s for _, s in games])
        for split, days in ((1, 7), (2, 15), (3, 30)):
            since = today - timedelta(days=days)
            aggregate(split, [s for g, s in games if self.date_of(g.sp) > since])
        stats, averages = self._projection(player, 70, 0.0)
        entries.append(
            {
                "id": f"10{self.season}",
                "externalId": str(self.season),
                "seasonId": self.season,
                "scoringPeriodId": 0,
                "statSourceId": 1,
                "statSplitTypeId": 0,
                "stats": stats,
                "averageStats": averages,
            }
        )
        if not player.rookie:
            stats, averages = self._projection(player, 64, 0.12)
            entries.append(
                {
                    "id": f"00{self.season - 1}",
                    "externalId": str(self.season - 1),
                    "seasonId": self.season - 1,
                    "scoringPeriodId": 0,
                    "statSourceId": 0,
                    "statSplitTypeId": 0,
                    "stats": stats,
                    "averageStats": averages,
                }
            )
        if game_logs:
            for game, line in games:
                entries.append(
                    {
                        "id": f"05{game.id}",
                        "externalId": str(game.id),
                        "seasonId": self.season,
                        "scoringPeriodId": game.sp,
                        "statSourceId": 0,
                        "statSplitTypeId": 5,
                        "proTeamId": player.pro_team,
                        "stats": {STAT_IDS[k]: v for k, v in line.items()},
                    }
                )
        return entries

    def _player_json(
        self, player: DemoPlayer, as_of: datetime, sp: int, game_logs: bool, days_back: float
    ) -> dict:
        arch = ARCHETYPES[player.arch]
        status = player.status(sp)
        owned = max(0.1, min(100.0, player.owned - player.change * days_back / 3))
        data: dict[str, Any] = {
            "id": player.id,
            "fullName": player.name,
            "firstName": player.name.split()[0],
            "lastName": player.name.split()[1],
            "proTeamId": player.pro_team,
            "defaultPositionId": arch["default"],
            "eligibleSlots": arch["slots"],
            "injured": status != "ACTIVE",
            "injuryStatus": status,
            "ownership": {
                "percentOwned": owned,
                "percentChange": player.change,
                "percentStarted": owned * 0.8,
            },
            "draftRanksByRankType": {
                "STANDARD": {"rank": max(1, int(400 - player.quality * 250 - player.base_min))}
            },
            "stats": self._stats_entries(player, as_of, game_logs),
        }
        if status != "ACTIVE" and player.return_offset is not None:
            back = self.date_of(self.today_sp + player.return_offset)
            data["injuryDetails"] = {"expectedReturnDate": [back.year, back.month, back.day]}
        return data

    def _ratings(self, player: DemoPlayer) -> dict:
        rank = max(1, int(260 - player.quality * 120 - player.base_min * 2))
        return {
            "0": {
                "positionalRanking": max(1, rank // 5),
                "totalRanking": rank,
                "totalRating": round(player.quality * player.base_min / 6, 2),
            }
        }

    def _wrapper(
        self,
        player: DemoPlayer,
        as_of: datetime,
        sp: int,
        status: str,
        on_team: int,
        game_logs: bool,
        days_back: float,
    ) -> dict:
        return {
            "id": player.id,
            "onTeamId": on_team,
            "status": status,
            "ratings": self._ratings(player),
            "player": self._player_json(player, as_of, sp, game_logs, days_back),
        }

    def _lineup(self, ids: list[int]) -> dict[int, int]:
        order = sorted(ids, key=lambda p: -self.players[p].quality * self.players[p].base_min)
        slots: dict[int, int] = {}
        for slot in (0, 1, 2, 3, 4, 5, 6, 11, 11, 11):
            for player_id in order:
                arch = ARCHETYPES[self.players[player_id].arch]
                if player_id not in slots and slot in arch["slots"]:
                    slots[player_id] = slot
                    break
        return {p: slots.get(p, 12) for p in ids}

    def _matchup_totals(self, ids: list[int], as_of: datetime, period: int) -> dict[str, float]:
        first_sp = (period - 1) * 7 + 1
        return self._totals(ids, as_of, range(first_sp, first_sp + 7))

    def _totals(self, ids: list[int], as_of: datetime, sps: range) -> dict[str, float]:
        """Stats of each day's ten busiest players with a game, summed."""
        totals = dict.fromkeys(STAT_IDS, 0.0)
        for sp in sps:
            lines = []
            for game in self._games_by_sp.get(sp, []):
                if game.start + timedelta(hours=3) > as_of:
                    continue
                for player_id in ids:
                    player = self.players[player_id]
                    if player.pro_team in (game.home, game.away):
                        stats = self._game_stats(player, game)
                        if stats:
                            lines.append(stats)
            for line in sorted(lines, key=lambda s: -s["min"])[:10]:
                for key, value in line.items():
                    totals[key] += value
        return totals

    def _schedule_item(
        self,
        item_id: int,
        item_period: int,
        current: int,
        home: int,
        away: int,
        rosters: dict[int, list[int]],
        as_of: datetime,
    ) -> dict:
        """One league matchup: next week's has no score yet, last week's is final."""
        item: dict[str, Any] = {
            "id": item_id,
            "matchupPeriodId": item_period,
            "winner": "UNDECIDED",
            "home": {"teamId": home},
            "away": {"teamId": away},
        }
        if item_period > current:
            return item
        mine = self._matchup_totals(rosters[home], as_of, item_period)
        theirs = self._matchup_totals(rosters[away], as_of, item_period)
        home_stats, home_record = self._score_by_stat(mine, theirs)
        away_stats, away_record = self._score_by_stat(theirs, mine)
        item["home"]["cumulativeScore"] = dict(
            zip(("wins", "losses", "ties"), home_record, strict=True), scoreByStat=home_stats
        )
        item["away"]["cumulativeScore"] = dict(
            zip(("wins", "losses", "ties"), away_record, strict=True), scoreByStat=away_stats
        )
        if item_period < current:
            wins, losses = home_record[0], home_record[1]
            item["winner"] = "HOME" if wins > losses else "AWAY" if losses > wins else "TIE"
        return item

    def _values_by_stat(self, ids: list[int], as_of: datetime, sp: int) -> dict[str, float]:
        totals = self._totals(ids, as_of, range(1, sp + 1))
        values = {
            STAT_IDS[k]: totals[k]
            for k in ("pts", "blk", "stl", "ast", "reb", "to", "fgm", "fga", "ftm", "fta", "tpm")
        }
        values["19"] = totals["fgm"] / totals["fga"] if totals["fga"] else 0.0
        values["20"] = totals["ftm"] / totals["fta"] if totals["fta"] else 0.0
        return values

    def _score_by_stat(self, mine: dict, theirs: dict) -> tuple[dict, list[int]]:
        def value(totals: dict, stat: str) -> float:
            if stat == "19":
                return totals["fgm"] / totals["fga"] if totals["fga"] else 0.0
            if stat == "20":
                return totals["ftm"] / totals["fta"] if totals["fta"] else 0.0
            key = next(k for k, v in STAT_IDS.items() if v == stat)
            return totals[key]

        out, record = {}, [0, 0, 0]
        for stat in CATEGORY_IDS:
            a, b = value(mine, stat), value(theirs, stat)
            if stat == "11":
                a, b = -a, -b
            result = "WIN" if a > b else "LOSS" if a < b else "TIE"
            record[("WIN", "LOSS", "TIE").index(result)] += 1
            out[stat] = {"score": value(mine, stat), "result": result}
        return out, record

    def bundle(self, as_of: datetime | None = None) -> dict[str, Any]:
        as_of = as_of or self.now
        days_back = (self.now - as_of).total_seconds() / 86400
        sp = self.sp_of(as_of.astimezone(EASTERN).date())
        period = (sp - 1) // 7 + 1
        rosters, free = self._rosters_at(as_of)

        teams = []
        for team_id, name in enumerate(TEAM_NAMES, 1):
            ids = rosters[team_id]
            lineup = self._lineup(ids)
            entries = []
            for player_id in ids + ([self.ir[team_id]] if team_id in self.ir else []):
                player = self.players[player_id]
                entries.append(
                    {
                        "playerId": player_id,
                        "lineupSlotId": 13
                        if player_id == self.ir.get(team_id)
                        else lineup[player_id],
                        "acquisitionType": "DRAFT",
                        "injuryStatus": player.status(sp),
                        "playerPoolEntry": self._wrapper(
                            player, as_of, sp, "ONTEAM", team_id, False, days_back
                        ),
                    }
                )
            in_period = [
                e
                for e in self.events
                if e.team == team_id
                and e.ts <= as_of
                and e.status == "EXECUTED"
                and (e.sp - 1) // 7 + 1 == period
            ]
            wins = 16 + (team_id * 7) % 11
            teams.append(
                {
                    "id": team_id,
                    "name": name,
                    "abbrev": "".join(w[0] for w in name.split())[:4].upper(),
                    "owners": [f"{{OWNER-{team_id}}}"],
                    "record": {"overall": {"wins": wins, "losses": 36 - wins - 2, "ties": 2}},
                    "waiverRank": (team_id * 3) % 10 + 1,
                    "transactionCounter": {
                        "acquisitions": 3 + team_id % 4 + len(in_period),
                        "matchupAcquisitionTotals": {str(period): len(in_period)},
                    },
                    "roster": {"entries": entries},
                    "valuesByStat": self._values_by_stat(ids, as_of, sp),
                }
            )

        schedule = []
        for item_period, pairs in (
            (period - 1, ((1, 10), (2, 3), (4, 5), (6, 7), (8, 9))),
            (period, ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10))),
            (period + 1, ((1, 3), (2, 4), (5, 7), (6, 8), (9, 10))),
        ):
            if item_period < 1:
                continue
            for home, away in pairs:
                schedule.append(
                    self._schedule_item(
                        len(schedule) + 1, item_period, period, home, away, rosters, as_of
                    )
                )

        # The rest of the regular season, as ESPN lists it: pairings only.
        for item_period in range(period + 2, 19):
            for home, away in _round_robin(item_period):
                schedule.append(
                    self._schedule_item(
                        len(schedule) + 1, item_period, period, home, away, rosters, as_of
                    )
                )

        league = {
            "id": DEMO_LEAGUE_ID,
            "seasonId": self.season,
            "scoringPeriodId": sp,
            "status": {
                "currentMatchupPeriod": period,
                "firstScoringPeriod": 1,
                "finalScoringPeriod": 140,
                "latestScoringPeriod": sp,
            },
            "settings": {
                "name": LEAGUE_NAME,
                "size": len(TEAM_NAMES),
                "scoringSettings": {
                    "scoringType": "H2H_CATEGORY",
                    "scoringItems": [
                        {"statId": int(s), "isReverseItem": s == "11"} for s in CATEGORY_IDS
                    ],
                },
                "rosterSettings": {
                    "lineupSlotCounts": {
                        "0": 1,
                        "1": 1,
                        "2": 1,
                        "3": 1,
                        "4": 1,
                        "5": 1,
                        "6": 1,
                        "7": 0,
                        "8": 0,
                        "9": 0,
                        "10": 0,
                        "11": 3,
                        "12": 2,
                        "13": 1,
                    },
                },
                "acquisitionSettings": {"matchupAcquisitionLimit": 5, "waiverHours": 24},
                "scheduleSettings": {
                    # 18 regular-season weeks, then two playoff weeks.
                    "matchupPeriodCount": 18,
                    "playoffTeamCount": 4,
                    # As ESPN sends it: the weeks each matchup covers.
                    "matchupPeriods": {str(k): [k] for k in range(1, 21)},
                },
            },
            "members": [
                {"id": f"{{OWNER-{i}}}", "displayName": f"manager{i}"}
                for i in range(1, len(TEAM_NAMES) + 1)
            ],
            "teams": teams,
            "schedule": schedule,
        }

        waived_recently = {
            e.dropped
            for e in self.events
            if e.dropped and e.ts <= as_of and as_of - e.ts < timedelta(days=1)
        }
        pool = [
            self._wrapper(
                self.players[p],
                as_of,
                sp,
                "WAIVERS" if p in waived_recently else "FREEAGENT",
                0,
                False,
                days_back,
            )
            for p in free
        ]
        pool.sort(key=lambda w: -w["player"]["ownership"]["percentOwned"])
        trending = sorted(pool, key=lambda w: -w["player"]["ownership"]["percentChange"])[:50]
        everyone = [p for ids in rosters.values() for p in ids] + list(self.ir.values()) + free

        return {
            "meta": {
                "fetched_at": as_of.isoformat(),
                "league_id": DEMO_LEAGUE_ID,
                "season": self.season,
            },
            "warnings": [],
            "league": league,
            "pro_schedule": self._pro_schedule(),
            "free_agents": {"players": pool[:150]},
            "free_agents_trending": {"players": trending},
            "player_cards": [
                {
                    "players": [
                        self._wrapper(self.players[p], as_of, sp, "", 0, True, days_back)
                        for p in everyone
                    ]
                }
            ],
            "transactions": [{"transactions": self._transactions(as_of)}],
            "players_index": [
                {
                    "id": p.id,
                    "fullName": p.name,
                    "proTeamId": p.pro_team,
                    "defaultPositionId": ARCHETYPES[p.arch]["default"],
                    "eligibleSlots": ARCHETYPES[p.arch]["slots"],
                }
                for p in self.players.values()
            ],
            "injuries": self._injuries(sp),
        }

    def _pro_schedule(self) -> dict:
        teams = [{"id": 0, "abbrev": "FA", "proGamesByScoringPeriod": {}}]
        for team_id in range(1, 31):
            by_sp: dict[str, list] = {}
            for game in self.games:
                if team_id in (game.home, game.away):
                    by_sp.setdefault(str(game.sp), []).append(
                        {
                            "id": game.id,
                            "date": int(game.start.timestamp() * 1000),
                            "homeProTeamId": game.home,
                            "awayProTeamId": game.away,
                            "scoringPeriodId": game.sp,
                        }
                    )
            teams.append(
                {"id": team_id, "abbrev": PRO_TEAMS[team_id], "proGamesByScoringPeriod": by_sp}
            )
        return {"settings": {"proTeams": teams}}

    def _transactions(self, as_of: datetime) -> list[dict]:
        rows = []
        for i, event in enumerate(self.events):
            if event.ts > as_of:
                continue
            ms = int(event.ts.timestamp() * 1000)
            items = []
            if event.added:
                items.append(
                    {
                        "type": "ADD",
                        "playerId": event.added,
                        "fromTeamId": 0,
                        "toTeamId": event.team,
                    }
                )
            if event.dropped:
                items.append(
                    {
                        "type": "DROP",
                        "playerId": event.dropped,
                        "fromTeamId": event.team,
                        "toTeamId": 0,
                    }
                )
            rows.append(
                {
                    "id": f"demo-{i}",
                    "type": event.kind,
                    "status": event.status,
                    "teamId": event.team,
                    "scoringPeriodId": event.sp,
                    "processDate": ms,
                    "proposedDate": ms - 3_600_000,
                    "items": items,
                }
            )
        return rows

    def _injuries(self, sp: int) -> dict:
        by_team: dict[int, list] = {}
        for player in self.players.values():
            status = player.status(sp)
            if status == "ACTIVE" or not player.injury:
                continue
            side, kind, detail = player.injury
            back = (
                self.date_of(self.today_sp + player.return_offset).isoformat()
                if player.return_offset is not None
                else None
            )
            by_team.setdefault(player.pro_team, []).append(
                {
                    "athlete": {
                        "displayName": player.name,
                        "links": [{"href": f"https://www.espn.com/nba/player/_/id/{player.id}/x"}],
                    },
                    "status": "Out" if status == "OUT" else "Day-To-Day",
                    "date": self.date_of(sp).isoformat() + "T12:00Z",
                    "shortComment": player.note,
                    "details": {"side": side, "type": kind, "detail": detail, "returnDate": back},
                }
            )
        return {
            "injuries": [
                {"displayName": PRO_TEAMS[team], "injuries": rows} for team, rows in by_team.items()
            ]
        }


def _round_robin(period: int, teams: int = 10) -> list[tuple[int, int]]:
    """A week of the circle method: team 1 stays put, the others rotate."""
    others = list(range(2, teams + 1))
    shift = period % len(others)
    ring = [1] + others[shift:] + others[:shift]
    return [(ring[i], ring[-1 - i]) for i in range(teams // 2)]
