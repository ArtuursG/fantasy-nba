"""The manager's brief: the whole picture in a size a chat assistant reads well.

The full report holds everything; this keeps what a manager decides with:
the league's rules and standings, where every team stands in each category,
this matchup and the opponent, my roster, a wide free agent pool (not just
the model's top pick), the trade market and the season picture. Model
suggestions are labelled as such, so the reader weighs them instead of
repeating them.
"""

from __future__ import annotations

from fantasy.report import num, pct, signed, table

FREE_AGENTS = 15
STREAMERS = 6
MODEL_MOVES = 3
TRADE_IDEAS = 3
NEED_TARGETS = 6

NOTES = """\
## NOTES FOR THE ASSISTANT
- You advise the manager of the team marked (me). Think like a manager over the
  whole season, not just tonight: standings and playoff seeding, which
  categories this roster can own, how to beat this week's opponent, the
  acquisition budget, and players' long-term value against one-week streams.
- Numbers come from my own model built on ESPN data. Lines marked "model" are
  its suggestions: test them, and say so when you disagree. Look across the
  whole free agent pool and trade market, not only the first names listed.
- Early in the season samples are small: weigh ESPN's projection, minutes,
  role and how widely a player is rostered across ESPN (%ROST) next to a few
  box scores.
- Give a short, prioritised plan with the reasoning behind each move; say
  "hold" when nothing is worth an acquisition."""


def render_brief(view: dict) -> str:
    out: list[str] = []
    add = out.extend
    m = view["meta"]
    rules = m.get("rules") or {}
    punt = ", ".join(m["punt"]) or "none"
    add(
        [
            f"# FANTASY MANAGER BRIEF {m['date']}",
            f"Data from ESPN as of {m['fetched_at']} ({m['timezone']}).",
            "",
            NOTES,
            "",
            "## LEAGUE",
            f"- {m['league']}: {m['teams']} teams, head-to-head, categories "
            f"{', '.join(m['categories'])} (TO: fewer is better). Each category won in a "
            "matchup counts as one win in the standings.",
        ]
    )
    if rules:
        acq = view.get("acquisitions") or {}
        add(
            [
                f"- Lineup: {rules.get('lineup', '-')}; at most {rules.get('c_limit', '-')} "
                "C-eligible starters. Acquisitions: "
                f"{acq.get('used', '-')}/{rules.get('acquisition_limit') or '-'} used this "
                "matchup. "
                f"Waivers: {rules.get('waiver_days', '-')} day(s).",
            ]
        )
    so = view.get("season_outlook")
    if so:
        add(
            [
                f"- Playoffs: top {so['playoff_teams']} of {m['teams']}; "
                f"{so['matchups_left']} regular-season matchups left after this one; playoff "
                f"weeks {', '.join(str(w) for w in so['playoff_weeks']) or '-'}.",
            ]
        )
    add([f"- My team: {m['my_team']}. Punting: {punt}."])

    _standings(view, add)
    _category_map(view, add)
    _todo(view, add)
    _matchup(view, add)
    _opponent(view, add)
    _roster(view, add)
    _free_agents(view, add)
    _trades(view, add)
    _next_matchup(view, add)
    _season(view, add)
    _activity(view, add)
    return "\n".join(out).strip() + "\n"


def _label(row: dict) -> str:
    return row["team"] + (" (me)" if row.get("is_me") else " (opp)" if row.get("is_opp") else "")


def _standings(view: dict, add) -> None:
    rows = view.get("season_standings")
    if not rows:
        return
    add(["", "## STANDINGS (as on ESPN; seed = current playoff seed)"])
    add(
        table(
            ["Seed", "Team", "Division", "W-L-T", "GB"],
            (
                [
                    r["seed"] or "-",
                    _label(r),
                    r["division"] or "-",
                    r["record"],
                    num(r["gb"]) if r["gb"] else "--",
                ]
                for r in rows
            ),
        )
    )


def _category_map(view: dict, add) -> None:
    rows = view.get("season_standings")
    teams = {t["name"]: t for t in view.get("teams") or []}
    if not rows:
        return
    cats = list(rows[0]["values"])
    add(
        [
            "",
            "## CATEGORY MAP (league rank 1-10, 1 best: season totals so far / roster "
            "projected per game)",
        ]
    )

    def cell(r: dict, cat: str) -> str:
        season = r["ranks"].get(cat, "-")
        strength = (teams.get(r["team"]) or {}).get("strength", {}).get("ranks", {}).get(cat)
        return f"{season}/{strength}" if strength else str(season)

    add(table(["Team", *cats], ([_label(r)] + [cell(r, c) for c in cats] for r in rows)))
    me = next((r for r in rows if r["is_me"]), None)
    if me:
        strong = [c for c in cats if me["ranks"].get(c, 99) <= 3]
        weak = [c for c in cats if me["ranks"].get(c, 0) >= 8]
        totals = ", ".join(
            f"{c} {pct(me['values'][c]) if c.endswith('%') else num(me['values'][c], 0)}"
            for c in cats
        )
        add(
            [
                f"My season totals: {totals}. Strong (top 3): {', '.join(strong) or '-'}; "
                f"weak (8th or worse): {', '.join(weak) or '-'}."
            ]
        )


def _todo(view: dict, add) -> None:
    actions = view.get("actions")
    if not actions or not actions["items"]:
        return
    add(["", "## MODEL CHECKS FOR TODAY (lineup, injuries, one simulated move)"])
    for item in actions["items"]:
        why = f" ({item['why']})" if item["why"] else ""
        add([f"- [{item['kind'].upper()}] {item['text']}{why}"])


def _matchup(view: dict, add) -> None:
    mu = view.get("matchup")
    if not mu:
        return
    o = mu["outlook"]
    score = mu["score_now"]
    add(
        [
            "",
            f"## THIS MATCHUP ({mu['period']}) vs {mu['opp']['name']}: {mu['dates'][0]} - "
            f"{mu['dates'][1]}",
            f"Score now {score['wins']}-{score['losses']}-{score['ties']}; model projects "
            f"{mu['projected_record']}, win chance {o['p_win_matchup'] * 100:.0f}%.",
        ]
    )
    current = {c["cat"]: c for c in mu["current"]}

    def fmt(cat: str, value: float | None) -> str:
        return pct(value) if cat.endswith("%") else num(value, 0)

    add(
        table(
            ["Cat", "Me now", "Opp now", "Me proj", "Opp proj", "Win %"],
            (
                [
                    p["cat"],
                    fmt(p["cat"], current.get(p["cat"], {}).get("me")),
                    fmt(p["cat"], current.get(p["cat"], {}).get("opp")),
                    fmt(p["cat"], p["me"]),
                    fmt(p["cat"], p["opp"]),
                    f"{p['p_win'] * 100:.0f}%",
                ]
                for p in mu["projected"]
            ),
        )
    )
    g = mu["games"]
    line = (
        f"Games: me {g['me']['played']} played, {g['me']['expected_total']:.1f} expected in "
        f"total; opponent {g['opp']['played']} played, {g['opp']['expected_total']:.1f} expected"
    )
    streams = mu.get("opp_streaming")
    if streams and streams["games"]:
        line += f" (incl. ~{streams['games']:.1f} games they are expected to stream)"
    add([line + "."])
    strategy = view.get("strategy")
    if strategy:
        parts = [
            f"{name} {', '.join(strategy[key])}"
            for key, name in (
                ("chase", "chase"),
                ("protect", "protect"),
                ("hold", "hold"),
                ("concede", "concede"),
                ("locked", "locked"),
            )
            if strategy.get(key)
        ]
        if parts:
            add([f"Model category plan: {'; '.join(parts)}."])
    grid = view.get("week_grid")
    days = [d for d in (grid or {}).get("days", []) if not d["past"]]
    if days:
        add(
            [
                "Days left (my starters with a game / my open slots / opponent starters / "
                "NBA games): "
                + "; ".join(
                    f"{d['label']} {d['starts']}/{d['open_slots']}/{d.get('opp_starts', '-')}"
                    f"/{d['nba_games']}"
                    for d in days
                )
            ]
        )


def _opponent(view: dict, add) -> None:
    opp = next((t for t in view.get("teams") or [] if t["is_opp"]), None)
    if not opp:
        return
    add(["", f"## OPPONENT: {opp['name']} ({opp['record']})"])
    standing = next((r for r in view.get("season_standings") or [] if r["is_opp"]), None)
    if standing:
        ranks = standing["ranks"]
        add(["- Season category ranks: " + ", ".join(f"{c} {ranks[c]}" for c in ranks) + "."])
    habit = next((h for h in view.get("habits") or [] if h["is_opp"]), None)
    moves = next((t for t in view.get("pickups") or [] if t["is_opp"]), None)
    acq = (moves or {}).get("acquisitions") or opp.get("acquisitions") or {}
    line = f"- Acquisitions this matchup: {acq.get('used', '-')}/{acq.get('limit', '-')}"
    if habit:
        line += (
            f"; adds about {habit['weekly_rate']:.1f} players a week"
            f"{' (assumed)' if habit['rate_basis'] != 'own pace' else ''}"
        )
        if habit.get("lost_per_week"):
            line += f"; leaves ~{habit['lost_per_week']:.1f} games a week on the bench"
    add([line + "."])
    if moves and (moves["adds"] or moves["drops"]):
        adds = ", ".join(a["name"] for a in moves["adds"]) or "none"
        add([f"- Last 7 days: added {adds}; dropped {', '.join(moves['drops']) or 'none'}."])
    stars = sorted(opp["roster"], key=lambda r: -(r.get("value") or -9))[:5]
    if stars:
        add(
            [
                "- Best players: "
                + ", ".join(f"{r['name']} ({r['health']}, {r['games_remaining']} g)" for r in stars)
                + "."
            ]
        )


def _roster(view: dict, add) -> None:
    me = view.get("my_team")
    if not me:
        return
    drops = set((view.get("moves") or {}).get("drop_candidates") or [])
    rankings = view.get("rankings") or {}
    period = next(
        (r["label"] for r in rankings.get("ranges", []) if r["key"] == rankings.get("default")),
        "the default period",
    )
    add(
        [
            "",
            "## MY ROSTER",
            "Per game: the model's line (season blended with ESPN's projection). "
            "Games = this matchup left/usable. Value = average z-score per category "
            f"(0 = an average rostered player in this league); # = rank among all players "
            f"({period}).",
        ]
    )
    add(
        table(
            ["Player", "Slot", "Status", "Role", "Games", "GP", "Per game", "%ROST", "Value"],
            (
                [
                    f"{r['name']} {r['positions']} {r['pro_team']}"
                    + (" [model drop candidate]" if r["name"] in drops else ""),
                    r["slot"] or "-",
                    _health(r),
                    _role(r),
                    f"{r['games_remaining']}/{r.get('usable_remaining', '-')}",
                    r.get("gp") or 0,
                    _line(r.get("proj_line") or {}),
                    _owned(r),
                    f"{signed(r['value'], 2)} (#{r.get('rank') or '-'})",
                ]
                for r in me["roster"]
            ),
        )
    )


def _free_agents(view: dict, add) -> None:
    fas = view.get("free_agents") or []
    if fas:
        add(
            [
                "",
                f"## FREE AGENT POOL (top {min(FREE_AGENTS, len(fas))} by the model: long-term "
                "value, %ROST, role and form; a sample, more exist)",
            ]
        )
        add(
            table(
                [
                    "Player",
                    "Avail.",
                    "Status",
                    "Role",
                    "Games",
                    "GP",
                    "Per game",
                    "%ROST",
                    "Value",
                    "Notes",
                ],
                (
                    [
                        f"{r['name']} {r['positions']} {r['pro_team']}",
                        _availability(r),
                        _health(r),
                        _role(r),
                        f"{r['games_remaining']}/{r.get('usable_remaining', '-')}",
                        r.get("gp") or 0,
                        _line(r.get("proj_line") or {}),
                        _owned(r),
                        signed(r["value"], 2),
                        "; ".join(x for x in r["reasons"] if "usable game" not in x)[:160] or "-",
                    ]
                    for r in fas[:FREE_AGENTS]
                ),
            )
        )
    popular = view.get("popular_free_agents") or []
    if popular:
        add(
            [
                "",
                "Most rostered free agents across ESPN (the market's view): "
                + "; ".join(
                    f"{p['name']} {p['pro_team']} {p['roster_pct']:.0f}%"
                    + (" WA" if p.get("waivers") else "")
                    + (f" {p['health']}" if p["health"] not in ("Healthy", None) else "")
                    for p in popular
                    if p.get("roster_pct") is not None
                ),
            ]
        )
    streamers = view.get("streamers") or []
    if streamers:
        add(
            [
                "Streaming options this matchup (games on days I have an open slot): "
                + "; ".join(
                    f"{r['name']} {r['pro_team']} {len(r.get('usable_days') or [])} "
                    f"({', '.join(d[:3] for d in r.get('usable_days') or []) or '-'})"
                    for r in streamers[:STREAMERS]
                ),
            ]
        )
    moves = (view.get("moves") or {}).get("moves") or []
    if moves:
        add(["Model simulation of single add/drops (change in this week's win chance):"])
        for mv in moves[:MODEL_MOVES]:
            cats = ", ".join(
                f"{c['cat']} {signed(c['change'], 2)}" for c in mv.get("category_changes", [])[:3]
            )
            add(
                [
                    f"- Add {mv['add']} ({mv['add_team']}), drop {mv['drop']}: "
                    f"{signed(mv['p_win_change'] * 100, 0)} pts to "
                    f"{mv['p_win_after'] * 100:.0f}%" + (f"; {cats}" if cats else "")
                ]
            )
    hot = view.get("hot_free_agents") or []
    if hot:
        add(
            [
                "Likely to be picked up by others soon: "
                + ", ".join(f"{h['name']} ({h['likelihood']})" for h in hot[:8])
            ]
        )


def _trades(view: dict, add) -> None:
    tt = view.get("trade_targets") or {}
    ideas = view.get("trade_ideas") or []
    rows = view.get("season_standings") or []
    if not (tt or ideas):
        return
    add(["", "## TRADE MARKET"])
    if tt.get("needs"):
        add([f"- Model: my roster most needs {', '.join(tt['needs'])}."])
    if rows:
        cats = list(rows[0]["ranks"])
        for r in rows:
            if r["is_me"]:
                continue
            strong = [c for c in cats if r["ranks"][c] <= 3]
            weak = [c for c in cats if r["ranks"][c] >= 8]
            add(
                [f"- {_label(r)}: strong {', '.join(strong) or '-'}; weak {', '.join(weak) or '-'}"]
            )
    targets = tt.get("need_targets") or []
    if targets:
        add(
            [
                "- Players on other teams who fit my needs: "
                + "; ".join(
                    f"{p['name']} ({p['positions']}, {p['owner']}, value {signed(p['value'], 2)})"
                    for p in targets[:NEED_TARGETS]
                )
            ]
        )
    for t in ideas[:TRADE_IDEAS]:
        add(
            [
                f"- Model trade idea with {t['partner']}: give "
                f"{', '.join(p['name'] for p in t['give'])}, get "
                f"{', '.join(p['name'] for p in t['get'])} (my average category rank "
                f"{t['avg_rank_before']} -> {t['avg_rank_after']}; helps "
                f"{', '.join(t['helps_me']) or '-'})"
            ]
        )


def _next_matchup(view: dict, add) -> None:
    nm = view.get("next_matchup")
    if not nm:
        return
    games = nm.get("games") or {}
    ranks = nm.get("ranks") or {}
    line = (
        f"## NEXT MATCHUP ({nm['period']}, {nm['dates'][0]} - {nm['dates'][1]}) vs "
        f"{nm['opponent']} ({nm['opponent_record']}): model win chance "
        f"{nm['outlook']['p_win_matchup'] * 100:.0f}%"
    )
    if games:
        line += f"; games scheduled me {games['me']['scheduled']}, them {games['opp']['scheduled']}"
    add(["", line + "."])
    if ranks:
        add(
            [
                "Roster category ranks me/them: "
                + ", ".join(f"{c} {r['me']}/{r['opp']}" for c, r in ranks.items())
            ]
        )


def _season(view: dict, add) -> None:
    so = view.get("season_outlook")
    punts = view.get("punt_analysis")
    if so:
        mine = next((r for r in so["rows"] if r["is_me"]), None)
        if mine:
            add(
                [
                    "",
                    f"## SEASON OUTLOOK: record {mine['record']}, model projects "
                    f"{mine['projected']}, playoff chance {mine['playoff_pct'] * 100:.0f}%, "
                    f"average seed {mine['avg_seed']}.",
                ]
            )
    if punts:
        rows = sorted(punts["rows"], key=lambda r: (r["place"], r["cost"]))[:4]
        add(
            [
                "Punt options (my place by average rank in the categories kept; cost = "
                "categories a week given up): "
                + "; ".join(f"{r['label']}: place {r['place']}, cost {r['cost']:.2f}" for r in rows)
            ]
        )


def _activity(view: dict, add) -> None:
    others = [t for t in view.get("pickups") or [] if not t["is_opp"] and t["adds"]]
    if others:
        add(
            [
                "",
                "## LEAGUE ACTIVITY (7 days, adds): "
                + "; ".join(
                    f"{t['team']}: {', '.join(a['name'] for a in t['adds'])}" for t in others
                ),
            ]
        )
    recap = view.get("recap")
    if recap:
        s = recap["score"]
        add(
            [
                "",
                f"Last matchup: {recap['result']} {s['wins']}-{s['losses']}-{s['ties']} vs "
                f"{recap['opponent']}. " + " ".join(recap["notes"]),
            ]
        )


def _health(r: dict) -> str:
    health = r.get("health") or "-"
    if r.get("expected_return") and health not in ("Healthy", "-"):
        health += f", back ~{r['expected_return'][5:]}"
    return health


def _role(r: dict) -> str:
    role = r.get("role") or "-"
    trend = r.get("trend")
    if trend in ("UP", "DOWN"):
        role += f", minutes {trend.lower()}"
    return role


def _owned(r: dict) -> str:
    owned = r.get("roster_pct")
    if owned is None:
        return "-"
    change = r.get("roster_pct_change")
    return f"{owned:.0f}%" + (f" ({change:+.1f})" if change else "")


def _availability(r: dict) -> str:
    if r.get("pool_status") == "WAIVERS" or r.get("owner") == "WA":
        clear = r.get("waiver_clear")
        return f"WA to {clear[5:10]}" if clear else "WA"
    return "FA"


def _line(line: dict) -> str:
    if not line:
        return "no stats"
    return (
        f"{num(line.get('min'), 0)} min, {num(line.get('pts'))} pts, {num(line.get('reb'))} reb, "
        f"{num(line.get('ast'))} ast, {num(line.get('tpm'))} 3pm, {num(line.get('stl'))} stl, "
        f"{num(line.get('blk'))} blk, {num(line.get('to'))} to, FG {pct(line.get('fg_pct'))}, "
        f"FT {pct(line.get('ft_pct'))}"
    )
