"""The short report: what to decide today, small enough for a chat prompt.

The full report holds everything; this keeps the parts a decision needs
(today's to-do, the matchup, my roster, the opponent, the best pickups,
trade ideas and the season picture), one line per item where it can.
"""

from __future__ import annotations

from fantasy.report import num, pct, signed, table

FREE_AGENTS = 8
TRADE_IDEAS = 3


def render_brief(view: dict) -> str:
    out: list[str] = []
    add = out.extend
    m = view["meta"]
    mu = view.get("matchup")
    punt = ", ".join(m["punt"]) or "none"
    add(
        [
            f"# FANTASY BRIEF {m['date']}",
            f"League: {m['league']} (ESPN {m['teams']}-team H2H, categories "
            f"{', '.join(m['categories'])}). My team: {m['my_team']}. Punt: {punt}. "
            f"Data: {m['fetched_at']} {m['timezone']}.",
        ]
    )

    actions = view.get("actions")
    if actions:
        add(["", "## TO DO NOW"])
        for item in actions["items"]:
            why = f" ({item['why']})" if item["why"] else ""
            add([f"- [{item['kind'].upper()}] {item['text']}{why}"])

    if mu:
        o = mu["outlook"]
        score = mu["score_now"]
        add(
            [
                "",
                f"## MATCHUP {mu['period']} vs {mu['opp']['name']} ({mu['dates'][0]} - "
                f"{mu['dates'][1]})",
                f"Now {score['wins']}-{score['losses']}-{score['ties']}; projected "
                f"{mu['projected_record']}; win chance {o['p_win_matchup'] * 100:.0f}%; expected "
                f"categories {o['expected_wins']:.1f} of {o['categories']}.",
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
        streams = mu.get("opp_streaming")
        line = (
            f"Games: me {g['me']['expected_total']:.1f} expected ({g['me']['played']} played), "
            f"opponent {g['opp']['expected_total']:.1f} ({g['opp']['played']} played)"
        )
        if streams and streams["games"]:
            line += f"; opponent's expected streaming included (+{streams['games']:.1f} games)"
        add([line + "."])

    grid = view.get("week_grid")
    if grid:
        days = [d for d in grid["days"] if not d["past"]]
        if days:
            add(["", "Days left (my starts / open slots / NBA games; pickup ideas):"])
            for d in days:
                ideas = "; ".join(
                    f"{i['name']} +{i['gain']:.2f} (drop {i['drop']})" for i in d.get("ideas", [])
                )
                add(
                    [
                        f"- {d['label']}: {d['starts']} / {d['open_slots']} / {d['nba_games']}"
                        + (f"; {ideas}" if ideas else "")
                    ]
                )

    me = view.get("my_team")
    if me:
        add(["", "## MY ROSTER (slot, status, games left/usable, last 15 days per game, value)"])
        for r in me["roster"]:
            line = r.get("last15") or r.get("season") or r.get("projected") or {}
            stats = _line(line) if line else "no stats"
            add(
                [
                    f"- {r['name']} {r['positions']} {r['pro_team']} | {r['slot'] or '-'} | "
                    f"{r['health']} | {r['games_remaining']}/{r.get('usable_remaining', '-')} | "
                    f"{stats} | {signed(r['value'], 2)}"
                ]
            )

    opp_moves = next((t for t in view.get("pickups") or [] if t["is_opp"]), None)
    if opp_moves:
        adds = ", ".join(a["name"] for a in opp_moves["adds"]) or "none"
        drops = ", ".join(opp_moves["drops"]) or "none"
        acq = opp_moves["acquisitions"]
        add(
            [
                "",
                f"## OPPONENT MOVES (7 days): added {adds}; dropped {drops}; acquisitions "
                f"{acq['used']}/{acq['limit']}.",
            ]
        )
    others = [t for t in view.get("pickups") or [] if not t["is_opp"]]
    if others:
        add(
            [
                "Other teams added: "
                + "; ".join(
                    f"{t['team']}: {', '.join(a['name'] for a in t['adds'])}"
                    for t in others
                    if t["adds"]
                )
            ]
        )

    fas = view.get("free_agents") or []
    if fas:
        add(["", "## TOP FREE AGENTS (games left/usable, last 15 days, value, why)"])
        for r in fas[:FREE_AGENTS]:
            line = r.get("last15") or r.get("season") or r.get("projected") or {}
            add(
                [
                    f"- {r['name']} {r['positions']} {r['pro_team']} | {r['health']} | "
                    f"{r['games_remaining']}/{r.get('usable_remaining', '-')} | "
                    f"{_line(line, short=True) if line else 'no stats'} | "
                    f"{signed(r['value'], 2)} | {'; '.join(r['reasons'][:2]) or '-'}"
                ]
            )
    hot = view.get("hot_free_agents") or []
    if hot:
        add(
            [
                "Likely to be picked up soon: "
                + ", ".join(f"{h['name']} ({h['likelihood']})" for h in hot)
            ]
        )

    ideas = view.get("trade_ideas") or []
    if ideas:
        add(["", "## TRADE IDEAS (my avg category rank before -> after)"])
        for t in ideas[:TRADE_IDEAS]:
            add(
                [
                    f"- With {t['partner']}: give {', '.join(p['name'] for p in t['give'])}, get "
                    f"{', '.join(p['name'] for p in t['get'])} | {t['avg_rank_before']} -> "
                    f"{t['avg_rank_after']} | helps me in {', '.join(t['helps_me']) or '-'}"
                ]
            )

    season = view.get("season_outlook")
    punts = view.get("punt_analysis")
    if season:
        mine = next((r for r in season["rows"] if r["is_me"]), None)
        if mine:
            line = (
                f"## SEASON: record {mine['record']}, projected {mine['projected']}, playoff "
                f"chance {mine['playoff_pct'] * 100:.0f}% (top {season['playoff_teams']}), "
                f"average seed {mine['avg_seed']}."
            )
            if punts and punts.get("best"):
                line += f" Best punt fit by the numbers: {punts['best']}."
            add(["", line])

    recap = view.get("recap")
    if recap:
        s = recap["score"]
        add(
            [
                "",
                f"Last week: {recap['result']} {s['wins']}-{s['losses']}-{s['ties']} vs "
                f"{recap['opponent']}. " + " ".join(recap["notes"]),
            ]
        )
    return "\n".join(out).strip() + "\n"


def _line(line: dict, short: bool = False) -> str:
    parts = [
        f"MIN {num(line.get('min'))}",
        f"PTS {num(line.get('pts'))}",
        f"REB {num(line.get('reb'))}",
        f"AST {num(line.get('ast'))}",
        f"3PM {num(line.get('tpm'))}",
        f"STL {num(line.get('stl'))}",
        f"BLK {num(line.get('blk'))}",
    ]
    if not short:
        parts += [
            f"TO {num(line.get('to'))}",
            f"FG {pct(line.get('fg_pct'))}",
            f"FT {pct(line.get('ft_pct'))}",
        ]
    return " ".join(parts)
