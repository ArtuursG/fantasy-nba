"""The daily ChatGPT report: Markdown, same sections in the same order every
day, so a model reading several days of reports can compare them."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from fantasy.timeutil import day_label, parse_iso

STAT_COLUMNS = [
    ("3PM", "tpm"),
    ("REB", "reb"),
    ("AST", "ast"),
    ("STL", "stl"),
    ("BLK", "blk"),
    ("TO", "to"),
    ("PTS", "pts"),
]
DETAILED_FREE_AGENTS = 15
RANKING_ROUNDS = 13
# Short names for the per-category value columns.
VALUE_LABELS = {
    "PTS": "pV",
    "3PM": "3V",
    "REB": "rV",
    "AST": "aV",
    "STL": "sV",
    "BLK": "bV",
    "FG%": "fg%V",
    "FT%": "ft%V",
    "TO": "toV",
}


def num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def pct(value: Any) -> str:
    return "-" if value is None else f"{value:.3f}"


def signed(value: Any, digits: int = 1) -> str:
    # Adding 0.0 turns a rounded -0.0 into 0.0, so it prints as +0.00.
    return "-" if value is None else f"{round(value, digits) + 0.0:+.{digits}f}"


def table(headers: list[str], rows: Iterable[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in row) + " |")
    return lines


def short_time(iso: str | None, tz_name: str) -> str:
    if not iso:
        return "-"
    return parse_iso(iso).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")


def line_text(line: dict | None, with_gp: bool = True) -> str:
    if not line:
        return "no stats"
    parts = []
    if with_gp:
        parts.append(f"{line['gp']:.0f} GP, {line['gs']:.0f} GS")
    parts.append(f"{line['min']:.1f} MIN")
    parts.append(f"{line['fgm']:.1f}/{line['fga']:.1f} FG {pct(line['fg_pct'])}")
    parts.append(f"{line['ftm']:.1f}/{line['fta']:.1f} FT {pct(line['ft_pct'])}")
    parts += [f"{line[key]:.1f} {label}" for label, key in STAT_COLUMNS]
    return " | ".join(parts)


def stats_source(row: dict) -> tuple[dict | None, str]:
    """Season averages, or ESPN's projection (marked *) before any games."""
    if row.get("season") and row["season"]["gp"] > 0:
        return row["season"], ""
    if row.get("projected"):
        return row["projected"], "*"
    return row.get("proj_line"), "*"


def stat_cells(line: dict | None) -> list[str]:
    if not line:
        return ["-"] * (2 + len(STAT_COLUMNS))
    return [pct(line["fg_pct"]), pct(line["ft_pct"])] + [num(line[k]) for _, k in STAT_COLUMNS]


def minutes_list(values: list[float]) -> str:
    return ", ".join(f"{m:.0f}" for m in values) if values else "-"


def rater_text(rater: dict) -> str:
    labels = {"season": "season", "last7": "last 7", "last15": "last 15", "last30": "last 30"}
    parts = []
    for key, label in labels.items():
        item = rater.get(key)
        if item and item.get("rank"):
            rating = f" ({item['rating']:.2f})" if item.get("rating") is not None else ""
            parts.append(f"{label} #{item['rank']}{rating}")
    return ", ".join(parts) if parts else "n/a"


def game_text(game: dict) -> str:
    day = game["date"][5:].replace("-", "/") if game.get("date") else "?"
    started = "S" if game["started"] else "B"
    fg = f"{game['fgm']:.0f}/{game['fga']:.0f}"
    return (
        f"{day} {started} {game['min']:.0f}m {game['pts']:.0f}p {game['reb']:.0f}r "
        f"{game['ast']:.0f}a {game['stl']:.0f}s {game['blk']:.0f}b {game['tpm']:.0f}x3 "
        f"{game['to']:.0f}to {fg}fg"
    )


def availability(row: dict) -> str:
    if row.get("pool_status") == "WAIVERS":
        clear = row.get("waiver_clear")
        if clear:
            when = parse_iso(clear).strftime("%m/%d %H:%M UTC")
            return f"WA (clears {when}{' est.' if row.get('waiver_clear_estimated') else ''})"
        return "WA"
    return "FA"


def value_text(row: dict, punt: list[str]) -> str:
    """'+0.45 (league +0.30), rank #12' for a player row."""
    text = signed(row.get("value"), 2)
    if punt:
        text += f" (league {signed(row.get('league_value'), 2)})"
    if row.get("rank"):
        text += f", rank #{row['rank']}"
    return text


def cat_values_text(values: dict[str, float], punt: list[str]) -> str:
    return " | ".join(
        f"{cat} {signed(v, 2)}{' (punted)' if cat in punt else ''}" for cat, v in values.items()
    )


def advanced_lines(adv: dict | None, short: bool = False) -> list[str]:
    if not adv:
        return []
    shooting = (
        f"TS% {pct(adv['ts_pct'])} | eFG% {pct(adv['efg_pct'])} | 3P% {pct(adv['tp_pct'])} on "
        f"{num(adv['tpa'])} 3PA"
    )
    cons = adv.get("consistency")
    consistency = (
        f"Game-to-game value (last {cons['games']}): average {signed(cons['mean'], 2)}, "
        f"spread {cons['sd']:.2f}, floor {signed(cons['floor'], 2)}, "
        f"ceiling {signed(cons['ceiling'], 2)}, bad games {cons['bad_games'] * 100:.0f}%"
        if cons
        else None
    )
    per36 = adv.get("per36")
    per36_text = (
        "Per 36: " + ", ".join(f"{v} {k.upper().replace('TPM', '3PM')}" for k, v in per36.items())
        if per36
        else None
    )
    if short:
        return [
            x for x in (f"Advanced: {shooting} | AST/TO {num(adv['ast_to'], 2)}", consistency) if x
        ]
    played = (
        f" | played {adv['games_played']} of {adv['team_games']} team games"
        if adv.get("team_games")
        else ""
    )
    lines = [
        f"Advanced ({adv['source']}): {shooting} | FTA/FGA {num(adv['ft_rate'], 2)} | AST/TO "
        f"{num(adv['ast_to'], 2)} | OREB {num(adv['oreb'])} / DREB {num(adv['dreb'])} | stocks "
        f"{num(adv['stocks'])} | double-doubles "
        + (f"{adv['dd_rate'] * 100:.0f}%" if adv["dd_rate"] is not None else "-")
        + f" of recent games{played}",
        per36_text,
        consistency,
    ]
    return [x for x in lines if x]


def health_text(row: dict) -> str:
    text = row["health"]
    if row.get("expected_return") and row["injury_status"] not in ("ACTIVE", "NORMAL"):
        text += f", back ~{row['expected_return']}"
    return text


class Report:
    def __init__(self, view: dict, compact: bool) -> None:
        self.view = view
        self.meta = view["meta"]
        self.compact = compact
        self.lines: list[str] = []

    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    def section(self, title: str) -> None:
        self.add("", f"## {title}", "")

    def render(self) -> str:
        self.header()
        self.rules()
        self.my_roster()
        self.alerts()
        self.matchup()
        self.transactions()
        self.free_agents()
        self.simulator()
        self.opponent_changes()
        self.schedule()
        self.acquisitions()
        self.waiver_order()
        self.important_changes()
        self.strength()
        self.season_totals()
        if not self.compact:
            self.rankings()
            self.all_rosters()
            self.week_changes()
        self.popular()
        self.notes()
        return "\n".join(self.lines).strip() + "\n"

    def header(self) -> None:
        m = self.meta
        self.add("# DAILY FANTASY REPORT", "")
        if m["demo"]:
            self.add("**DEMO DATA: invented league, not real players or stats.**", "")
        dates = m["matchup_dates"]
        span = ""
        if dates[0] and dates[1]:
            span = f" ({_label(dates[0])} - {_label(dates[1])})"
        self.add(
            f"Date: {m['date']}",
            f"League: {m['league']} (ESPN, {m['teams']}-team H2H categories, "
            f"season {m['season_label']})",
            f"My Team: {m['my_team'] or 'not found (set FANTASY_TEAM)'}",
            f"Data fetched: {m['fetched_at']} {m['timezone']} | ESPN scoring period "
            f"{m['scoring_period']} | Matchup {m['matchup_period']}{span}",
        )
        if m["compared_with"]:
            week = f"; 7-day view vs {m['week_ago']}" if m["week_ago"] else ""
            self.add(f"Compared with: snapshot of {m['compared_with']}{week}")
        else:
            self.add("Compared with: no earlier snapshot yet (changes start with the next day)")

    def rules(self) -> None:
        m = self.meta
        rules = m["rules"]
        cats = ", ".join(f"{c} (lower is better)" if c == "TO" else c for c in m["categories"])
        self.section("LEAGUE RULES")
        self.add(
            f"Categories: {cats}",
            f"Lineup: {rules['lineup']}",
            f"Max {rules['c_limit']} C-eligible players on the roster "
            f"(you have {self.view['my_c_count']})",
            f"Waivers: {rules['waiver_days']} day | Max {rules['acquisition_limit']} acquisitions "
            "per matchup | Daily lineup changes",
        )
        if m["punt"]:
            self.add(
                f"Strategy: punting {', '.join(m['punt'])}. Player values and rankings leave "
                f"{'it' if len(m['punt']) == 1 else 'them'} out; the matchup section still "
                "covers every category."
            )

    def my_roster(self) -> None:
        self.section("MY ROSTER")
        team = self.view["my_team"]
        if not team:
            self.add("My team was not found in the league (check FANTASY_TEAM).")
            return
        self.add(
            f"{team['name']} | record {team['record']} | waiver #{team['waiver_rank'] or '-'}",
            "Stats are season per-game averages (* = ESPN projection, no games yet). "
            "Games left / Usable are for this matchup.",
            "",
        )
        rows = []
        for r in team["roster"]:
            line, mark = stats_source(r)
            rows.append(
                [
                    r["name"] + mark,
                    r["pro_team"],
                    r["positions"],
                    r["slot"] or "-",
                    health_text(r),
                    r["gp"],
                    num(line["min"] if line else None),
                    minutes_list(r["last5_min"]),
                    *stat_cells(line),
                    r["games_remaining"],
                    r["usable_remaining"] if r["usable_remaining"] is not None else "-",
                    signed(r["value"], 2),
                    r["rank"] or "-",
                ]
            )
        self.add(
            *table(
                [
                    "Player",
                    "Team",
                    "Pos",
                    "Slot",
                    "Health",
                    "GP",
                    "MIN",
                    "Last5 MIN",
                    "FG%",
                    "FT%",
                    *(label for label, _ in STAT_COLUMNS),
                    "Games left",
                    "Usable",
                    "Value",
                    "Rank",
                ],
                rows,
            )
        )
        self.add("", "### Player details")
        for r in team["roster"]:
            self.player_details(r)

    def player_details(self, r: dict) -> None:
        self.add(
            "",
            f"**{r['name']}** ({r['pro_team']}, {r['positions'] or '?'}) | slot {r['slot'] or '-'}"
            f" | {health_text(r)}",
        )
        if r.get("injury_note"):
            self.add(f"- Injury: {r['injury_note']}")
        own = (
            f"{num(r['roster_pct'])}% ({signed(r['roster_pct_change'])})"
            if r["roster_pct"] is not None
            else "n/a"
        )
        self.add(
            f"- Eligible: {r['eligible'] or '-'} | Roster {own} | ESPN rater: "
            f"{rater_text(r['rater'])} | Draft rank {r['draft_rank'] or '-'}",
            f"- Season: {line_text(r['season'])}",
            f"- Last 7 days: {line_text(r['last7'])}",
            f"- Last 15 days: {line_text(r['last15'])}",
        )
        if not r["season"] and r["projected"]:
            self.add(f"- ESPN projection: {line_text(r['projected'], with_gp=False)}")
        punt = self.meta["punt"]
        self.add(
            f"- Value: {value_text(r, punt)} | per category: "
            f"{cat_values_text(r['cat_values'], punt)}"
        )
        for line in advanced_lines(r.get("advanced")):
            self.add(f"- {line}")
        if r["last5_games"]:
            self.add("- Last 5 games: " + "; ".join(game_text(g) for g in r["last5_games"]))
        usage = f"usage proxy {num(r['usage_proxy'])}"
        if r["usage_proxy_last5"] is not None:
            usage += f" (last 5: {num(r['usage_proxy_last5'])})"
        self.add(
            f"- Minutes last 5: {minutes_list(r['last5_min'])} | Starts last 5: "
            f"{r['last5_starts']}/{len(r['last5_min'])} | {usage}",
            f"- Role: {r['role']} | Trend: {r['trend']}"
            + (
                f" ({signed(r['min_delta'])} MIN vs {r['baseline_label']})"
                if r["min_delta"] is not None
                else ""
            ),
            f"- Matchup: {r['games_matchup']} games, {r['games_remaining']} left "
            f"({', '.join(r['game_days']) or 'none'}), usable {r['usable_remaining'] or 0}, "
            f"back-to-backs this matchup {r['b2b']}",
        )

    def alerts(self) -> None:
        self.section("INJURY / ROLE CHANGES")
        alerts = self.view["alerts"]
        if not alerts:
            self.add("No role or injury changes detected.")
            return
        for alert in alerts:
            self.add(
                f"**{alert['name']}** ({alert['pro_team']}) | {alert['owner']} | {alert['trend']}"
            )
            self.add(*(f"- {line}" for line in alert["lines"]), "")

    def matchup(self) -> None:
        self.section("CURRENT MATCHUP")
        mu = self.view["matchup"]
        if not mu:
            self.add("No current matchup found (off week, or my team not found).")
            return
        score = mu["score_now"]
        self.add(
            f"{mu['me']['name']} vs {mu['opp']['name']}",
            f"Opponent: {mu['opp']['name']}",
            f"Matchup {mu['period']}: {mu['dates'][0]} - {mu['dates'][1]}",
            f"Current score: {score['wins']}-{score['losses']}-{score['ties']} (W-L-T)",
            "",
            "Current:",
        )

        def value(cat: str, v: Any) -> str:
            return pct(v) if cat.endswith("%") else num(v, 0)

        leader = {"me": "me", "opp": "opp", "tie": "tie", None: "-"}
        self.add(
            *table(
                ["Cat", "Me", "Opp", "Leader"],
                (
                    [
                        c["cat"],
                        value(c["cat"], c["me"]),
                        value(c["cat"], c["opp"]),
                        leader[c["leader"]],
                    ]
                    for c in mu["current"]
                ),
            )
        )
        self.add("", "Projected final:")
        self.add(
            *table(
                ["Cat", "Me", "Opp", "Win %", "Call"],
                (
                    [
                        p["cat"],
                        value(p["cat"], p["me"]),
                        value(p["cat"], p["opp"]),
                        f"{p['p_win'] * 100:.0f}%",
                        p["call"],
                    ]
                    for p in mu["projected"]
                ),
            )
        )
        games = mu["games"]
        self.add(
            "",
            f"Likely win: {', '.join(mu['likely_wins']) or 'none'}",
            f"Likely loss: {', '.join(mu['likely_losses']) or 'none'}",
            f"Swing: {', '.join(mu['swing']) or 'none'}",
            f"Projected result: {mu['projected_record']} (W-L-T)",
            f"Games left: me {games['me']['scheduled_remaining']} scheduled / "
            f"{games['me']['usable_remaining']} usable; opponent "
            f"{games['opp']['scheduled_remaining']} / {games['opp']['usable_remaining']}",
        )
        outlook = mu["outlook"]
        at_least = {int(k): v for k, v in outlook["p_at_least"].items()}
        n = outlook["categories"]
        half = n // 2 + 1
        self.add(
            "",
            f"Win chances: expected categories won {outlook['expected_wins']:.1f} of {n}; chance "
            f"to win the matchup (more categories than the opponent): "
            f"{outlook['p_win_matchup'] * 100:.0f}%",
            "Category wins: "
            + ", ".join(
                f"at least {k}: {at_least[k] * 100:.0f}%"
                for k in range(max(0, half - 1), min(n, half + 2) + 1)
            ),
        )
        if mu["targets"]:
            punt = self.meta["punt"]
            self.add("", "What it takes (categories short of a likely win):", "")
            rows = []
            for t in mu["targets"]:
                pct_cat = t["cat"].endswith("%")
                fmt = (lambda v: f"{v:.3f}") if pct_cat else (lambda v: f"{v:.1f}")
                unit = " fewer" if t["cat"] == "TO" else ""
                likely = fmt(t["to_likely"]) + unit
                per_game = f"{t['per_game']:.2f}"
                if pct_cat and t["makes_to_likely"] is not None:
                    likely += f" (~{t['makes_to_likely']:.0f} more makes)"
                    per_game += " makes"
                rows.append(
                    [
                        t["cat"] + (" (punted)" if t["cat"] in punt else ""),
                        f"{t['p_win'] * 100:.0f}%",
                        signed(t["edge"], 3 if pct_cat else 1),
                        fmt(t["to_even"]) + (unit if t["to_even"] else ""),
                        likely,
                        per_game,
                    ]
                )
            self.add(
                *table(
                    ["Cat", "Win %", "Projected edge", "To draw even", "To 70%", "Per game left"],
                    rows,
                )
            )
        if mu["attempts_estimated"]:
            self.add(
                "(Current FGA/FTA are not in ESPN's matchup data; they are estimated from "
                "the lineups played so far to project FG% and FT%.)"
            )

    def transactions(self) -> None:
        self.section("LEAGUE TRANSACTIONS SINCE LAST REPORT")
        rows = self.view["transactions"]
        if not rows:
            self.add("No transactions in the last 7 days.")
            return
        new = [r for r in rows if r["new"]]
        self.add(
            f"{len(new)} new since the last report; full last 7 days below ([NEW] = since last "
            "report).",
            "",
        )
        for r in rows:
            self.add("- " + self.transaction_text(r))

    def transaction_text(self, r: dict) -> str:
        actions = [f"ADD {n}" for n in r["adds"]] + [f"DROP {n}" for n in r["drops"]]
        actions += [f"TRADE {t}" for t in r["trades"]]
        extra = f" | {r['result']}" if r["result"] else ""
        extra += f" | bid ${r['bid']:.0f}" if r["bid"] else ""
        mark = "[NEW] " if r["new"] else ""
        when = short_time(r["ts"], self.meta["timezone"])
        moves = ", ".join(actions) or "-"
        return f"{mark}{when} | {r['team']} | {moves} | Source: {r['source']}{extra}"

    def free_agents(self) -> None:
        self.section("TOP FREE AGENTS")
        fas = self.view["free_agents"]
        if not fas:
            self.add("No free agents in the data.")
            return
        self.add(
            "Ranked by interest: value plus recent form, minutes trend, new starting role, injured "
            "teammates, return from injury, add rate and usable games for my roster.",
        )
        detailed = fas[:DETAILED_FREE_AGENTS]
        for i, r in enumerate(detailed, 1):
            line, mark = stats_source(r)
            label = "Projection" if mark else "Season"
            self.add(
                "",
                f"{i}. **{r['name']}**",
                f"   Team: {r['pro_team']} | Position: {r['positions'] or '?'} ({r['eligible']}) | "
                f"Status: {availability(r)}",
                f"   Health: {health_text(r)} | Roster: {num(r['roster_pct'])}% "
                f"({signed(r['roster_pct_change'])})",
                f"   Projected minutes: {num(r['projected_min'])}"
                + (
                    f" (ESPN preseason projection {num(r['espn_projected_min'])})"
                    if r["espn_projected_min"] is not None
                    and abs(r["espn_projected_min"] - r["projected_min"]) >= 4
                    else ""
                ),
                f"   {label}: {line_text(line, with_gp=not mark)}",
                f"   Last 5: {line_text(r['last5'], with_gp=False)}",
                f"   Last 5 MIN: {minutes_list(r['last5_min'])} | Starts last 5: "
                f"{r['last5_starts']}/{len(r['last5_min'])}",
                f"   Current role: {r['role']} | Role trend: {r['trend']}"
                + (f" ({signed(r['min_delta'])} MIN)" if r["min_delta"] is not None else ""),
                f"   Usable games this matchup: {r['usable_remaining']} of {r['games_remaining']}"
                + (f" ({', '.join(r['usable_days'])})" if r["usable_days"] else ""),
                f"   Value: {value_text(r, self.meta['punt'])}",
                *(f"   {line}" for line in advanced_lines(r.get("advanced"), short=True)),
                f"   Why: {'; '.join(r['reasons']) or 'value'}",
            )
        rest = fas[DETAILED_FREE_AGENTS:]
        if rest and not self.compact:
            self.add("", f"More free agents ({DETAILED_FREE_AGENTS + 1}-{len(fas)}):", "")
            rows = []
            for i, r in enumerate(rest, DETAILED_FREE_AGENTS + 1):
                line, mark = stats_source(r)
                rows.append(
                    [
                        i,
                        r["name"] + mark,
                        r["pro_team"],
                        r["positions"],
                        availability(r),
                        r["health"],
                        num(r["roster_pct"]),
                        signed(r["roster_pct_change"]),
                        num(line["min"] if line else None),
                        minutes_list(r["last5_min"]),
                        r["trend"],
                        *stat_cells(line),
                        signed(r["value"], 2),
                        r["usable_remaining"],
                        "; ".join(r["reasons"][:2]),
                    ]
                )
            self.add(
                *table(
                    [
                        "#",
                        "Player",
                        "Team",
                        "Pos",
                        "Status",
                        "Health",
                        "Ros%",
                        "+/-",
                        "MIN",
                        "Last5 MIN",
                        "Trend",
                        "FG%",
                        "FT%",
                        *(label for label, _ in STAT_COLUMNS),
                        "Value",
                        "Usable",
                        "Why",
                    ],
                    rows,
                )
            )
        streamers = self.view["streamers"]
        if streamers:
            self.add("", "### Streaming targets (games on days with an open starting slot)", "")
            self.add(
                *table(
                    [
                        "Player",
                        "Team",
                        "Pos",
                        "Health",
                        "Usable",
                        "Games left",
                        "Days",
                        "MIN",
                        "Value",
                    ],
                    (
                        [
                            r["name"],
                            r["pro_team"],
                            r["positions"],
                            r["health"],
                            r["usable_remaining"],
                            r["games_remaining"],
                            ", ".join(r["usable_days"]),
                            num(r["projected_min"]),
                            signed(r["value"], 2),
                        ]
                        for r in streamers
                    ),
                )
            )

    def simulator(self) -> None:
        self.section("ADD/DROP SIMULATOR")
        sim = self.view.get("moves")
        if not sim or not sim["moves"]:
            self.add("No current matchup to simulate.")
            return
        base = sim["base"]
        acq = sim["acquisitions_left"]
        self.add(
            f"Now: expected categories won {base['expected_wins']:.1f}, matchup win chance "
            f"{base['p_win_matchup'] * 100:.0f}%. Each row adds the free agent in place of the "
            f"weakest player it helps most to drop ({', '.join(sim['drop_candidates'])}), from the "
            "day he can play (waiver players once they clear), and re-projects the rest of the "
            f"matchup. Acquisitions left this matchup: {acq if acq is not None else '?'}.",
            "",
        )
        if acq == 0:
            self.add("No acquisitions left: these moves only count from the next matchup.", "")
        rows = []
        for m in sim["moves"]:
            changes = ", ".join(
                f"{c['cat']} {c['change'] * 100:+.0f}%" for c in m["category_changes"][:3]
            )
            rows.append(
                [
                    m["add"],
                    m["add_team"],
                    m["drop"],
                    m["waiver_until"] or "now",
                    f"{m['usable_change']:+d}",
                    f"{m['expected_wins_change']:+.2f}",
                    f"{m['p_win_after'] * 100:.0f}% ({m['p_win_change'] * 100:+.0f})",
                    changes or "-",
                    signed(m["value_change"], 2),
                ]
            )
        self.add(
            *table(
                [
                    "Add",
                    "Team",
                    "Drop",
                    "Playable from",
                    "Usable games",
                    "Exp. cats",
                    "Matchup win %",
                    "Biggest category changes",
                    "Season value",
                ],
                rows,
            )
        )

    def season_totals(self) -> None:
        rows = self.view.get("season_standings")
        if not rows:
            return
        self.section("SEASON CATEGORY TOTALS (actual, rank 1 = best)")
        cats = list(rows[0]["values"])
        self.add("Season-to-date category totals from ESPN; TO ranked low-is-best.", "")
        self.add(
            *table(
                ["Team", "Record", *cats, "Avg rank"],
                (
                    [
                        r["team"] + (" (me)" if r["is_me"] else " (opp)" if r["is_opp"] else ""),
                        r["record"],
                        *(r["ranks"].get(c, "-") for c in cats),
                        f"{r['avg_rank']:.1f}",
                    ]
                    for r in rows
                ),
            )
        )
        self.add("", "Totals:", "")
        self.add(
            *table(
                ["Team", *cats],
                (
                    [r["team"]]
                    + [
                        pct(r["values"].get(c)) if c.endswith("%") else num(r["values"].get(c), 0)
                        for c in cats
                    ]
                    for r in rows
                ),
            )
        )

    def opponent_changes(self) -> None:
        self.section("OPPONENT ROSTER CHANGES")
        mu = self.view["matchup"]
        opp = next((t for t in self.view["teams"] if t["is_opp"]), None)
        if not mu or not opp:
            self.add("No current opponent.")
            return
        moves = [m for m in self.view["changes"]["roster_moves"] if m["is_opp"]]
        injuries = [
            i for i in self.view["changes"]["injuries"] if i["owner"].startswith("OPPONENT")
        ]
        recent = [t for t in self.view["transactions"] if t["team_id"] == opp["id"]]
        if not (moves or injuries or recent):
            self.add(f"{opp['name']}: no roster moves or injury changes since the last report.")
        for move in moves:
            if move["added"]:
                self.add(f"- Added since last report: {', '.join(move['added'])}")
            if move["dropped"]:
                self.add(f"- Dropped since last report: {', '.join(move['dropped'])}")
        for item in injuries:
            self.add(f"- {item['name']} injury: {item['from']} -> {item['to']}")
        if recent:
            self.add("- Transactions in the last 7 days:")
            self.add(*(f"  - {self.transaction_text(t)}" for t in recent))
        acq = opp["acquisitions"]
        self.add(
            "",
            f"{opp['name']}: record {opp['record']} | acquisitions this matchup "
            f"{acq['used']}/{acq['limit']} | games left {opp['games_remaining']} "
            f"(usable {opp['usable_remaining']})",
            "",
        )
        self.roster_table(opp["roster"])

    def roster_table(self, roster: list[dict], slim: bool = False) -> None:
        """A fantasy roster; `slim` leaves the per-game stats to PLAYER RANKINGS."""
        rows = []
        for r in roster:
            line, mark = stats_source(r)
            stats = [] if slim else stat_cells(line)
            rows.append(
                [
                    r["name"] + mark,
                    r["pro_team"],
                    r["positions"],
                    r["slot"] or "-",
                    health_text(r),
                    signed(r["value"], 2),
                    r["rank"] or "-",
                    num(line["min"] if line else None),
                    minutes_list(r["last5_min"]),
                    r["trend"],
                    *stats,
                    num(r["roster_pct"]),
                    r["games_remaining"],
                ]
            )
        stat_headers = [] if slim else ["FG%", "FT%", *(label for label, _ in STAT_COLUMNS)]
        self.add(
            *table(
                [
                    "Player",
                    "Team",
                    "Pos",
                    "Slot",
                    "Health",
                    "Value",
                    "Rank",
                    "MIN",
                    "Last5 MIN",
                    "Trend",
                    *stat_headers,
                    "Ros%",
                    "Games left",
                ],
                rows,
            )
        )

    def schedule(self) -> None:
        self.section("SCHEDULE")
        sched = self.view["schedule"]
        mu = self.view["matchup"]
        my_team = self.view["my_team"]
        if my_team:
            self.add(
                f"My remaining games: {my_team['games_remaining']} scheduled, "
                f"{my_team['usable_remaining']} usable"
            )
        if mu:
            games = mu["games"]["opp"]
            self.add(
                f"Opponent remaining games: {games['scheduled_remaining']} scheduled, "
                f"{games['usable_remaining']} usable"
            )
        self.add(
            f"Low-volume NBA days (<=5 games): {', '.join(sched['low_volume_days']) or 'none'}",
            f"High-volume NBA days (>=10 games): {', '.join(sched['high_volume_days']) or 'none'}",
            "",
        )
        if sched["days"]:
            self.add(
                *table(
                    [
                        "Day",
                        "NBA games",
                        "Volume",
                        "My players playing",
                        "My open slots",
                        "Benched (no slot)",
                        "Out",
                        "Opp playing",
                        "Opp open slots",
                    ],
                    (
                        [
                            d["label"],
                            d["nba_games"],
                            d["volume"],
                            f"{len(d['my_playing'])}: {', '.join(d['my_playing']) or '-'}",
                            f"{d['my_open_slots']} ({', '.join(d['my_open_slot_names']) or '-'})",
                            ", ".join(d["my_benched"]) or "-",
                            ", ".join(d["my_out"]) or "-",
                            d["opp_playing"],
                            "-" if d["opp_open_slots"] is None else d["opp_open_slots"],
                        ]
                        for d in sched["days"]
                    ),
                )
            )
        else:
            self.add("No games left in this matchup.")
        if my_team:
            self.add("", "My players' remaining games:")
            for r in my_team["roster"]:
                if r["slot"] == "IR":
                    continue
                days = ", ".join(r["game_days"]) or "none"
                self.add(
                    f"- {r['name']}: {r['games_remaining']} left ({days}), usable "
                    f"{r['usable_remaining'] or 0}, back-to-backs this matchup {r['b2b']}"
                )

    def acquisitions(self) -> None:
        self.section("ACQUISITIONS")
        acq = self.view["acquisitions"]
        if not acq:
            self.add("Unknown (my team not found).")
            return
        self.add(
            "Used this matchup:",
            f"{acq['used']} / {acq['limit']}",
            "Remaining:",
            f"{acq['remaining']}",
        )
        if acq["season_total"] is not None:
            self.add(f"Season total acquisitions: {acq['season_total']}")
        if acq["counted_from_transactions"]:
            self.add("(Counted from this matchup's transactions; ESPN gave no matchup total.)")
        ir = self.view["my_ir"]
        if ir:
            self.add("", "IR status:")
            if ir["players"]:
                for p in ir["players"]:
                    back = f", expected back {p['expected_return']}" if p["expected_return"] else ""
                    self.add(f"- IR slot: {p['name']} ({p['health']}{back})")
            else:
                self.add(f"- IR slot empty ({ir['slots']} available)")
            self.add(*(f"- {flag}" for flag in ir["flags"]))

    def waiver_order(self) -> None:
        self.section("WAIVER ORDER")
        for item in self.view["waiver_order"]:
            mark = " (you)" if item["is_me"] else ""
            self.add(f"{item['rank'] or '-'}. {item['team']}{mark}")

    def important_changes(self) -> None:
        self.section("IMPORTANT CHANGES SINCE YESTERDAY")
        changes = self.view["changes"]
        if changes["since"] is None:
            self.add("First snapshot: nothing to compare with yet.")
            return
        bullets = changes["bullets"]
        if not bullets:
            self.add("No important changes since the last snapshot.")
        for bullet in bullets[:25]:
            self.add(f"- {bullet}")
        if len(bullets) > 25:
            self.add(f"- ... and {len(bullets) - 25} smaller changes")

    def strength(self) -> None:
        self.section("CATEGORY STRENGTH (projected, rank 1 = best)")
        cats = self.meta["categories"]
        self.add(
            "Per-game output of each roster's healthy, non-IR players from the projection line; "
            "TO ranked low-is-best.",
            "",
        )
        teams = sorted(
            self.view["teams"],
            key=lambda t: (
                sum(t["strength"]["ranks"].values()) / max(len(t["strength"]["ranks"]), 1)
            ),
        )
        rows = []
        for t in teams:
            ranks = t["strength"]["ranks"]
            avg = sum(ranks.values()) / len(ranks) if ranks else 0
            name = t["name"] + (" (me)" if t["is_me"] else " (opp)" if t["is_opp"] else "")
            rows.append([name, *(ranks.get(c, "-") for c in cats), f"{avg:.1f}"])
        self.add(*table(["Team", *cats, "Avg rank"], rows))
        self.add("", "Category values (per game):", "")
        value_rows = []
        for t in teams:
            values = t["strength"]["values"]
            value_rows.append(
                [t["name"]]
                + [pct(values.get(c)) if c.endswith("%") else num(values.get(c)) for c in cats]
            )
        self.add(*table(["Team", *cats], value_rows))
        if self.compact:
            return
        for t in teams:
            ranks = t["strength"]["ranks"]
            if not ranks:
                continue
            by_rank = sorted(ranks.items(), key=lambda kv: kv[1])
            self.add("", f"Team: {t['name']}")
            self.add(*(f"{cat} rank: {ranks[cat]}" for cat in cats if cat in ranks))
            self.add(
                f"Strongest: {', '.join(c for c, _ in by_rank[:3])} | Weakest: "
                f"{', '.join(c for c, _ in by_rank[-3:])}"
            )

    def rankings(self) -> None:
        rankings = self.view["rankings"]
        key = rankings["default"]
        label = next(r["label"] for r in rankings["ranges"] if r["key"] == key)
        self.section("PLAYER RANKINGS")
        rows = rankings["rows"][key]
        if not rows:
            self.add("No player stats to rank yet.")
            return
        punt = self.meta["punt"]
        teams = self.meta["teams"]
        cats = rankings["categories"]
        self.add(
            f"Range: {label} | top {RANKING_ROUNDS} rounds ({RANKING_ROUNDS * teams} players) by "
            + ("punt value" if punt else "value")
            + ". Values are per-game z-scores against the rostered players (about +1 for a "
            "first-rounder, 0 at the edge of rosterable)."
            + (
                f" Punting {', '.join(punt)}: Value leaves it out, LeagV counts it." if punt else ""
            ),
            "Owner: ME = my team, OPP = current opponent, team abbreviations: "
            + ", ".join(f"{t['abbrev']} = {t['name']}" for t in self.view["teams"] if t["abbrev"])
            + ". USG is the usage proxy, (FGA + 0.44 FTA + TO) per 36 minutes.",
            "",
        )
        value_heads = ["Value", "LeagV", "Punt+"] if punt else ["Value"]
        headers = [
            "Rnd",
            "Rank",
            *value_heads,
            "Name",
            "Team",
            "Pos",
            "Owner",
            "Inj",
            "G",
            "MIN",
            "PTS",
            "3PM",
            "REB",
            "AST",
            "STL",
            "BLK",
            "FG%",
            "FGA",
            "FT%",
            "FTA",
            "TO",
            "USG",
            *(VALUE_LABELS.get(c, c) for c in cats),
            "L15 Value",
        ]
        body = []
        for r in rows[: RANKING_ROUNDS * teams]:
            values = [signed(r["value"], 2)]
            if punt:
                values += [
                    signed(r["league_value"], 2),
                    signed(r["value"] - r["league_value"], 2),
                ]
            body.append(
                [
                    r["round"],
                    r["rank"],
                    *values,
                    r["name"],
                    r["pro_team"],
                    r["positions"],
                    r["owner_short"],
                    r["injury"] or "-",
                    r["gp"],
                    num(r["min"]),
                    num(r["pts"]),
                    num(r["tpm"]),
                    num(r["reb"]),
                    num(r["ast"]),
                    num(r["stl"]),
                    num(r["blk"]),
                    pct(r["fg_pct"]),
                    num(r["fga"]),
                    pct(r["ft_pct"]),
                    num(r["fta"]),
                    num(r["to"]),
                    num(r["usage_proxy"]),
                    *(signed(r["values"].get(c), 2) for c in cats),
                    signed(r.get("last15_value"), 2),
                ]
            )
        self.add(*table(headers, body))

    def all_rosters(self) -> None:
        self.section("ALL TEAM ROSTERS")
        for t in self.view["teams"]:
            if t["is_me"]:
                continue
            acq = t["acquisitions"]
            tag = " (current opponent)" if t["is_opp"] else ""
            self.add(
                f"### {t['name']}{tag}",
                f"Record {t['record']} | waiver #{t['waiver_rank'] or '-'} | acquisitions this "
                f"matchup {acq['used']}/{acq['limit']} | games left {t['games_remaining']} "
                f"(usable {t['usable_remaining']})",
                "",
            )
            self.roster_table(t["roster"], slim=True)
            self.add("")

    def week_changes(self) -> None:
        self.section("CHANGES VS 7 DAYS AGO")
        changes = self.view["changes_week"]
        if changes["since"] is None:
            self.add("No snapshot from 7 days ago yet.")
            return
        for bullet in changes["bullets"][:20]:
            self.add(f"- {bullet}")
        if not changes["bullets"]:
            self.add("No notable changes over the week.")

    def popular(self) -> None:
        self.section("MOST ROSTERED FREE AGENTS")
        rows = self.view["popular_free_agents"]
        if not rows:
            self.add("None.")
            return
        self.add(
            *table(
                ["Player", "Team", "Pos", "Health", "Ros%", "+/-"],
                (
                    [
                        r["name"],
                        r["pro_team"],
                        r["positions"],
                        r["health"],
                        num(r["roster_pct"]),
                        signed(r["roster_pct_change"]),
                    ]
                    for r in rows
                ),
            )
        )

    def notes(self) -> None:
        self.section("DATA NOTES")
        self.add(
            "- Source: ESPN Fantasy API (league, rosters, free agents, transactions, game logs) "
            "and ESPN's NBA injury report.",
            '- "Last 15 days" is ESPN\'s own split; ESPN has no 14-day split.',
            "- Projection line: season averages blended with ESPN's projection (worth 10 games), "
            "then 35% weight on the last 15 days.",
            '- Usage %: ESPN doesn\'t publish it; "usage proxy" is (FGA + 0.44 FTA + TO) per 36 '
            "minutes.",
            "- Usable games: days a player gets a starting slot in the best possible lineup "
            "(positions respected, best players first); for free agents, days with an open slot "
            "he can fill on the current roster.",
            "- Win %: remaining output treated as random around the projection; 70%+ is a "
            "likely win, 30% or less a likely loss.",
            "- Role trend: last-5 minutes vs the 10 games before (or season average); 4+ MIN is "
            "UP/DOWN. Expected minutes from an injured teammate are an estimate.",
            "- Roster % and its change are across all ESPN leagues.",
            "- Value: average per-game z-score against the rostered players, percentages "
            "weighted by attempts and turnovers counted against; about +1 is a first-round "
            "player, 0 the edge of rosterable. Rank is by value in the PLAYER RANKINGS range; "
            "L15 Value uses the last 15 days.",
            "- Matchup win chance: categories treated as independent (they're not quite: a big "
            "night lifts several at once), so read it as a guide. Category wins are counted, so "
            "every expected category matters even when the matchup is decided.",
            "- What it takes: extra output needed over the remaining days to draw even and to "
            "reach a 70% chance, with the same per remaining usable game.",
            "- Add/drop simulator: the rest of the matchup re-projected with the pickup in place "
            "of the drop; season value is the difference in per-game value.",
            "- Game-to-game value: each recent game scored like the rankings; spread is the "
            "standard deviation, floor and ceiling the 20th and 80th percentile, bad games "
            "below -0.5.",
        )
        for warning in self.meta["warnings"]:
            self.add(f"- Warning: {warning}")


def _label(iso_date: str) -> str:
    return day_label(date.fromisoformat(iso_date))


def render_report(view: dict, compact: bool = False) -> str:
    return Report(view, compact).render()
