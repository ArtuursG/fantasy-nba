"""ESPN fantasy basketball (fba) identifiers.

Stat, slot and team ids match what ESPN's v3 API returns and what the
open-source espn-api client maps them to.
"""

FANTASY_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

# Stat id -> field on models.StatLine.
STAT_FIELDS = {
    "0": "pts",
    "1": "blk",
    "2": "stl",
    "3": "ast",
    "4": "oreb",
    "5": "dreb",
    "6": "reb",
    "11": "to",
    "13": "fgm",
    "14": "fga",
    "15": "ftm",
    "16": "fta",
    "17": "tpm",
    "18": "tpa",
    "40": "min",
}
STAT_GS = "41"
STAT_GP = "42"

# Stat id -> name used for matchup scores and league categories.
STAT_NAMES = {
    "0": "PTS",
    "1": "BLK",
    "2": "STL",
    "3": "AST",
    "6": "REB",
    "11": "TO",
    "13": "FGM",
    "14": "FGA",
    "15": "FTM",
    "16": "FTA",
    "17": "3PM",
    "18": "3PA",
    "19": "FG%",
    "20": "FT%",
    "21": "3P%",
    "40": "MIN",
}

DEFAULT_CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "TO", "PTS"]

# Lineup slot ids.
SLOT_NAMES = {
    0: "PG",
    1: "SG",
    2: "SF",
    3: "PF",
    4: "C",
    5: "G",
    6: "F",
    7: "SG/SF",
    8: "G/F",
    9: "PF/C",
    10: "F/C",
    11: "UTIL",
    12: "BE",
    13: "IR",
}
POSITION_SLOTS = (0, 1, 2, 3, 4)
C_SLOT = 4
BENCH_SLOT = 12
IR_SLOT = 13
NON_STARTING_SLOTS = {BENCH_SLOT, IR_SLOT, 14, 15}

# This league: PG, SG, SF, PF, C, G, F, UTIL x3, BE x2, IR x1.
DEFAULT_LINEUP_SLOTS = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 11: 3, 12: 2, 13: 1}

DEFAULT_POSITIONS = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}

# Fallback when the schedule response carries no abbreviations.
PRO_TEAMS = {
    0: "FA",
    1: "ATL",
    2: "BOS",
    3: "NOP",
    4: "CHI",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GSW",
    10: "HOU",
    11: "IND",
    12: "LAC",
    13: "LAL",
    14: "MIA",
    15: "MIL",
    16: "MIN",
    17: "BKN",
    18: "NYK",
    19: "ORL",
    20: "PHI",
    21: "PHX",
    22: "POR",
    23: "SAC",
    24: "SAS",
    25: "OKC",
    26: "UTA",
    27: "WAS",
    28: "TOR",
    29: "MEM",
    30: "CHA",
}

# Injury statuses that keep a player out of tonight's lineup.
UNAVAILABLE_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION"}
HEALTH_LABELS = {
    "ACTIVE": "Healthy",
    "NORMAL": "Healthy",
    "PROBABLE": "Probable",
    "DAY_TO_DAY": "DTD",
    "QUESTIONABLE": "Questionable",
    "DOUBTFUL": "Doubtful",
    "OUT": "OUT",
    "INJURY_RESERVE": "OUT (IR)",
    "SUSPENSION": "Suspended",
}

# Stat split ids: statSourceId (0 actual, 1 projected) + statSplitTypeId.
SPLIT_KEYS = {
    (0, 0): "season",
    (0, 1): "last7",
    (0, 2): "last15",
    (0, 3): "last30",
    (1, 0): "projected",
}
RATING_KEYS = {"0": "season", "1": "last7", "2": "last15", "3": "last30"}

TRANSACTION_TYPES = ["FREEAGENT", "WAIVER", "WAIVER_ERROR", "TRADE_ACCEPT"]
