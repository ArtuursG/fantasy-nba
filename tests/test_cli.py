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


def test_daily_appends_the_lineup_check_to_a_summary(env):
    summary = Path(env, "summary.md")
    summary.write_text("earlier step\n", encoding="utf-8")
    assert main(["daily", "--demo", "--summary", str(summary), "--notify"]) == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## Fantasy daily, ")
    assert "```text" in text


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


def test_punt_and_league_url_settings():
    from fantasy.config import parse_league_url, parse_punt

    assert parse_punt("to, FT ;3") == ("TO", "FT%", "3PM")
    assert parse_punt("") == ()
    with pytest.raises(ConfigError):
        parse_punt("TO, DUNKS")
    url = "https://fantasy.espn.com/basketball/team?leagueId=987654&teamId=3&seasonId=2027"
    assert parse_league_url(url) == {"league_id": 987654, "team_id": 3, "season": 2027}
    config = load_config({"ESPN_LEAGUE_URL": url, "FANTASY_DATA_DIR": "/tmp/x"})
    assert (config.league_id, config.season, config.team) == (987654, 2027, "3")
    named = load_config({"ESPN_LEAGUE_URL": url, "FANTASY_TEAM": "Bullu Kojas"})
    assert named.team == "Bullu Kojas"


def test_settings_are_saved_to_dev_vars(env, monkeypatch):
    import os

    from fantasy.app import FantasyApp
    from fantasy.config import SETTINGS_KEYS

    for key in SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)
    dev_vars = env / ".dev.vars"
    dev_vars.write_text("# mine\nFANTASY_TZ=Europe/Riga\nESPN_LEAGUE_ID=1\n", encoding="utf-8")
    app = FantasyApp(load_config())
    url = "https://fantasy.espn.com/basketball/league?leagueId=555&teamId=7"
    settings = app.update_settings(
        {"league_url": url, "espn_s2": "AEB%2Fs2", "swid": "ABC", "team": "", "punt": "to"}
    )
    assert settings["league_id"] == 555 and settings["team"] == "7"
    assert settings["has_espn_s2"] and settings["has_swid"] and settings["punt"] == ["TO"]
    text = dev_vars.read_text(encoding="utf-8")
    assert "# mine" in text and "FANTASY_TZ=Europe/Riga" in text
    assert "ESPN_LEAGUE_ID=\n" in text and f"ESPN_LEAGUE_URL={url}" in text
    assert os.environ["ESPN_S2"] == "AEB%2Fs2"

    # blank cookie fields keep what is saved
    app.update_settings({"espn_s2": "", "punt": ""})
    assert app.config.espn_s2 == "AEB%2Fs2" and app.config.punt == ()
    with pytest.raises(ConfigError):
        app.update_settings({"league_url": "https://fantasy.espn.com/basketball/players/add"})
