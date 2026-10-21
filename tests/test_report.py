import re

from fantasy.report import render_report

SECTIONS = [
    "TO DO NOW",
    "LEAGUE RULES",
    "TODAY'S LINEUP CHECK",
    "MY ROSTER",
    "INJURY / ROLE CHANGES",
    "WHAT OTHER TEAMS PICKED UP (LAST 7 DAYS)",
    "CURRENT MATCHUP",
    "GAMES THIS MATCHUP",
    "MY WEEK BY DAY",
    "CATEGORY STRATEGY THIS MATCHUP",
    "LEAGUE TRANSACTIONS SINCE LAST REPORT",
    "TOP FREE AGENTS",
    "FREE AGENTS LIKELY TO GO SOON",
    "ADD/DROP SIMULATOR",
    "STREAMING PLAN",
    "OPPONENT ROSTER CHANGES",
    "SCHEDULE",
    "NEXT MATCHUP PREVIEW",
    "ACQUISITIONS",
    "WAIVER ORDER",
    "IMPORTANT CHANGES SINCE YESTERDAY",
    "CATEGORY STRENGTH (projected, rank 1 = best)",
    "SEASON CATEGORY TOTALS (actual, rank 1 = best)",
    "SEASON OUTLOOK",
    "MANAGER HABITS",
    "TRADE TARGETS",
    "PLAYER RANKINGS",
    "ALL TEAM ROSTERS",
    "CHANGES VS 7 DAYS AGO",
    "MOST ROSTERED FREE AGENTS",
    "FORECAST ACCURACY",
    "DATA NOTES",
]


def test_full_report_has_every_section_in_order(view):
    text = render_report(view)
    headers = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headers == SECTIONS
    assert text.startswith("# DAILY FANTASY REPORT\n")
    assert "**DEMO DATA" in text
    assert "Date: 2026-10-15" in text
    assert "My Team: Home Team" in text
    assert "Opponent: Sabiles Stealers" in text
    acq = view["acquisitions"]
    assert f"Used this matchup:\n{acq['used']} / 5\nRemaining:\n{acq['remaining']}" in text
    assert re.search(r"## WAIVER ORDER\n\n1\. \S", text)
    assert "Likely win:" in text and "Swing:" in text
    assert "Team: Sabiles Stealers\nFG% rank:" in text
    for bad in (r"\bNone\b", r"\bnan\b", r"[{}]"):
        assert not re.search(bad, text), bad


def test_compact_report_drops_the_long_appendices(view):
    full, compact = render_report(view), render_report(view, compact=True)
    assert len(compact) < len(full) * 0.7
    assert "## ALL TEAM ROSTERS" not in compact
    assert "More free agents (16-50)" not in compact
    assert "## TOP FREE AGENTS" in compact


def test_report_is_stable_for_the_same_view(view):
    assert render_report(view) == render_report(view)


def test_markdown_tables_have_consistent_columns(view):
    for block in re.findall(r"((?:^\|.*\|\n)+)", render_report(view), flags=re.MULTILINE):
        widths = {line.count("|") for line in block.strip().splitlines()}
        assert len(widths) == 1, block[:200]


def test_report_lists_what_other_teams_picked_up(view):
    rows = view["pickups"]
    assert rows and all(r["team_id"] != view["meta"]["my_team_id"] for r in rows)
    assert [r["is_opp"] for r in rows] == sorted((r["is_opp"] for r in rows), reverse=True)
    add = next(a for r in rows for a in r["adds"])
    assert add["name"] and add["source"] and add["positions"]
    text = render_report(view)
    section = text.split("## WHAT OTHER TEAMS PICKED UP")[1].split("\n## ")[0]
    assert f"- ADD {add['name']} (" in section and "acquisitions this matchup" in section


def test_to_do_list_leads_the_report(view):
    actions = view["actions"]
    kinds = [i["kind"] for i in actions["items"]]
    # The demo has a starter without a game and an opponent with moves left.
    assert "lineup" in kinds and "opponent" in kinds
    assert actions["todo_count"] == sum(k in ("lineup", "check", "pickup") for k in kinds)
    text = render_report(view)
    section = text.split("## TO DO NOW")[1].split("\n## ")[0]
    assert "[LINEUP] Start " in section and "win chance" in section
    assert text.index("## TO DO NOW") < text.index("## LEAGUE RULES")
