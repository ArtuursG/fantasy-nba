from datetime import date
from pathlib import Path

import pytest

from fantasy.cli import main
from fantasy.config import ConfigError, default_season, load_config, normalise_swid


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key in ("ESPN_LEAGUE_ID", "ESPN_SEASON", "ESPN_S2", "ESPN_SWID", "FANTASY_TEAM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FANTASY_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # keep any real .dev.vars out of the way
    monkeypatch.setattr("fantasy.config.PROJECT_DIR", tmp_path)
    return tmp_path


def test_demo_refresh_then_report_to_a_file(env, capsys):
    assert main(["refresh", "--demo"]) == 0
    assert "Saved snapshot of Wolfy Tribute Federation (demo)" in capsys.readouterr().out
    out = env / "report.md"
    assert main(["report", "--demo", "--compact", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# DAILY FANTASY REPORT")


def test_daily_writes_a_dated_report(env):
    assert main(["daily", "--demo"]) == 0
    reports = list(Path(env, "reports").glob("*.md"))
    assert len(reports) == 1


def test_report_before_any_refresh_fails_cleanly(env, capsys):
    assert main(["report"]) == 1
    assert "fantasy refresh" in capsys.readouterr().err


def test_live_refresh_needs_a_league_id(env, capsys):
    assert main(["refresh"]) == 1
    assert "ESPN_LEAGUE_ID" in capsys.readouterr().err


def test_season_is_the_year_the_nba_season_ends():
    assert default_season(date(2026, 10, 15)) == 2027
    assert default_season(date(2027, 3, 1)) == 2027
    assert default_season(date(2027, 7, 31)) == 2027


def test_config_values():
    config = load_config(
        {
            "ESPN_LEAGUE_ID": "123456",
            "ESPN_S2": " abc ",
            "ESPN_SWID": "ABCD-1234",
            "FANTASY_TEAM": "Bullu Kojas",
            "FANTASY_DATA_DIR": "/tmp/x",
        },
        today=date(2026, 10, 15),
    )
    assert (config.league_id, config.season, config.espn_s2) == (123456, 2027, "abc")
    assert config.swid == "{ABCD-1234}" and config.team == "Bullu Kojas"
    assert normalise_swid("{X}") == "{X}" and normalise_swid("") is None
    with pytest.raises(ConfigError):
        load_config({"ESPN_LEAGUE_ID": "abc"})
    with pytest.raises(ConfigError):
        load_config({"FANTASY_TZ": "Mars/Base"})
