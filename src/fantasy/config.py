"""Settings from environment variables, with a .dev.vars file for local use.

Real environment variables always win over the file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TEAM = "Rembates Hektors IR"
DEFAULT_TZ = "Europe/Riga"


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
    return Config(
        league_id=_int(env, "ESPN_LEAGUE_ID"),
        season=_int(env, "ESPN_SEASON") or default_season(today or date.today()),
        espn_s2=(env.get("ESPN_S2") or "").strip() or None,
        swid=normalise_swid(env.get("ESPN_SWID")),
        team=(env.get("FANTASY_TEAM") or DEFAULT_TEAM).strip(),
        tz=tz,
        data_dir=data_dir,
        gamelog_days=_int(env, "FANTASY_GAMELOG_DAYS") or 30,
        fa_pool=_int(env, "FANTASY_FA_POOL") or 150,
    )
