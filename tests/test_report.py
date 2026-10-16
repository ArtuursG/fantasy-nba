import re

from fantasy.report import render_report

SECTIONS = [
    "LEAGUE RULES",
    "TODAY'S LINEUP CHECK",
    "MY ROSTER",
    "INJURY / ROLE CHANGES",
    "CURRENT MATCHUP",
    "CATEGORY STRATEGY THIS MATCHUP",
    "LEAGUE TRANSACTIONS SINCE LAST REPORT",
    "TOP FREE AGENTS",
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
