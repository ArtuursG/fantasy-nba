"""Settings from environment variables, with a .dev.vars file for local use.

Real environment variables always win over the file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TEAM = "Rembates Hektors IR"
DEFAULT_TZ = "Europe/Riga"
CATEGORY_ALIASES = {
    "FG": "FG%",
    "FG%": "FG%",
    "FT": "FT%",
    "FT%": "FT%",
    "3": "3PM",
    "3P": "3PM",
    "3PM": "3PM",
    "3PTM": "3PM",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "TO": "TO",
    "TOV": "TO",
    "PTS": "PTS",
}
# Keys the dashboard's settings form may write to .dev.vars.
SETTINGS_KEYS = (
    "ESPN_LEAGUE_URL",
    "ESPN_LEAGUE_ID",
    "ESPN_SEASON",
    "ESPN_S2",
    "ESPN_SWID",
    "FANTASY_TEAM",
    "FANTASY_PUNT",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    league_id: int | None
    season: int
    espn_s2: str | None
    swid: str | None
    team: str
    tz: ZoneInfo
    data_dir: Path
    gamelog_days: int = 30
    fa_pool: int = 150
    punt: tuple[str, ...] = ()
    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    def db_path(self, demo: bool = False) -> Path:
        return self.data_dir / ("demo.db" if demo else "fantasy.db")


def default_season(today: date) -> int:
    """ESPN files an NBA season under the year it ends; from August on the
    next season is the current one."""
    return today.year + 1 if today.month >= 8 else today.year


def load_dev_vars(paths: list[Path] | None = None) -> None:
    for path in paths or [PROJECT_DIR / ".dev.vars", Path.cwd() / ".dev.vars"]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip())


def _int(env: Mapping[str, str], key: str) -> int | None:
    value = (env.get(key) or "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise ConfigError(f"{key} must be a number, got {value!r}")
    return int(value)


def normalise_swid(value: str | None) -> str | None:
    """ESPN's SWID cookie includes its curly braces; add them if pasted bare."""
    if not value:
        return None
    value = value.strip()
    return value if value.startswith("{") else "{" + value.strip("{}") + "}"


def parse_punt(value: str | None) -> tuple[str, ...]:
    """'TO, ft%' -> ('TO', 'FT%'): the categories a punt strategy ignores."""
    found: list[str] = []
    for part in re.split(r"[,;\s]+", (value or "").upper()):
        if not part:
            continue
        cat = CATEGORY_ALIASES.get(part)
        if cat is None:
            raise ConfigError(f"FANTASY_PUNT: unknown category {part!r} (for example TO or FT%)")
        if cat not in found:
            found.append(cat)
    return tuple(found)


def parse_league_url(url: str | None) -> dict[str, int]:
    """League, team and season ids from any ESPN fantasy basketball page URL,
    e.g. .../basketball/team?leagueId=123&teamId=4&seasonId=2027."""
    if not url:
        return {}
    query = {k.lower(): v for k, v in parse_qs(urlsplit(url.strip()).query).items()}
    found = {}
    for key, name in (("leagueid", "league_id"), ("teamid", "team_id"), ("seasonid", "season")):
        value = (query.get(key) or [""])[0]
        if value.isdigit():
            found[name] = int(value)
    return found


def load_config(env: Mapping[str, str] | None = None, today: date | None = None) -> Config:
    if env is None:
        load_dev_vars()
        env = os.environ
    tz_name = env.get("FANTASY_TZ") or DEFAULT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"Unknown FANTASY_TZ {tz_name!r}") from exc
    data_dir = Path(env.get("FANTASY_DATA_DIR") or PROJECT_DIR / "data")
    from_url = parse_league_url(env.get("ESPN_LEAGUE_URL"))
    team = (env.get("FANTASY_TEAM") or "").strip()
    if not team:
        team = str(from_url["team_id"]) if "team_id" in from_url else DEFAULT_TEAM
    return Config(
        league_id=_int(env, "ESPN_LEAGUE_ID") or from_url.get("league_id"),
        season=(
            _int(env, "ESPN_SEASON")
            or from_url.get("season")
            or default_season(today or date.today())
        ),
        espn_s2=(env.get("ESPN_S2") or "").strip() or None,
        swid=normalise_swid(env.get("ESPN_SWID")),
        team=team,
        tz=tz,
        data_dir=data_dir,
        gamelog_days=_int(env, "FANTASY_GAMELOG_DAYS") or 30,
        fa_pool=_int(env, "FANTASY_FA_POOL") or 150,
        punt=parse_punt(env.get("FANTASY_PUNT")),
        telegram_token=(env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None,
        telegram_chat_id=(env.get("TELEGRAM_CHAT_ID") or "").strip() or None,
    )


def save_settings(updates: Mapping[str, str], path: Path | None = None) -> Path:
    """Write settings into .dev.vars, keeping its other lines, and apply them
    to this process too (the file only fills in variables not yet set)."""
    path = path or PROJECT_DIR / ".dev.vars"
    for key, value in updates.items():
        if key not in SETTINGS_KEYS:
            raise ConfigError(f"{key} can't be set from the dashboard")
        if "\n" in value or "\r" in value:
            raise ConfigError(f"{key} must be a single line")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, written = [], set()
    for line in lines:
        key = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in updates:
            out.append(f"{key}={updates[key].strip()}")
            written.add(key)
        else:
            out.append(line)
    out += [f"{k}={v.strip()}" for k, v in updates.items() if k not in written]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for key, value in updates.items():
        if value.strip():
            os.environ[key] = value.strip()
        else:
            os.environ.pop(key, None)
    return path
