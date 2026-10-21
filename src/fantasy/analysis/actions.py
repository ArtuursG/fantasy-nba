"""Today's to-do list: the few things worth doing before lineup lock.

Built from the rest of the view (lineup check, streaming plan, opponent
moves, category plan), so it says nothing the detailed panels don't; it
only puts the actionable parts first and in order.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# A pickup is suggested only when it moves the matchup this much.
MIN_PICKUP_GAIN = 0.15
RECENT_HOURS = 36


def build_actions(view: dict) -> dict:
    items: list[dict] = []
    lineup = view.get("lineup")
    if lineup:
        lock = lineup["lock"][11:] if lineup.get("lock") else None
        for s in lineup["swaps"]:
            text = (
                f"Start {s['start']} in {s['slot']} for {s['for']}"
                if s["for"]
                else f"Start {s['start']}: rearrange the slots to fit him"
            )
            items.append(_item("lineup", text, s["reason"], s.get("tipoff") or lock))
        for b in lineup["bench"]:
            items.append(_item("lineup", f"Bench {b['name']}", b["reason"], lock))
        for flag in lineup["ir"]:
            items.append(_item("lineup", flag, None, None))
        for w in lineup["watch"]:
            items.append(_item("check", f"Check {w} before lock", "injury report", lock))

    plan = view.get("stream_plan")
    if plan and plan["steps"]:
        step = plan["steps"][0]
        if step["gain"] >= MIN_PICKUP_GAIN:
            before = plan["base"]["p_win_matchup"]
            verb = "Claim" if step["waiver"] else "Add"
            items.append(
                _item(
                    "pickup",
                    f"{verb} {step['add']} ({step['add_team']}), drop {step['drop']}",
                    f"+{step['gain']:.1f} expected categories, win chance "
                    f"{before * 100:.0f}% → {step['p_win_after'] * 100:.0f}%",
                    step["day"],
                    player_id=step["add_id"],
                )
            )

    matchup = view.get("matchup") or {}
    streaming = matchup.get("opp_streaming")
    if streaming and streaming["expected_adds"] >= 0.5:
        items.append(
            _item(
                "opponent",
                f"Opponent likely streams ~{streaming['expected_adds']:.1f} more player(s), "
                f"about {streaming['games']:.0f} extra games",
                f"{streaming['acquisitions_left']} acquisitions left, "
                f"{streaming['weekly_rate']:.1f} per week ({streaming['basis']}); "
                "already in the win chance",
                None,
            )
        )
    since = _parse(view["meta"]["fetched_at_iso"]) - timedelta(hours=RECENT_HOURS)
    for team in view.get("pickups") or []:
        if not team["is_opp"]:
            continue
        for add in team["adds"]:
            if add["ts"] and _parse(add["ts"]) >= since:
                items.append(
                    _item(
                        "opponent",
                        f"Opponent added {add['name']} ({add['positions']}, {add['pro_team']})",
                        f"{add['games_left']} games left this matchup"
                        if add["games_left"] is not None
                        else None,
                        None,
                        player_id=add["id"],
                    )
                )

    strategy = view.get("strategy")
    if strategy:
        chase = [r["cat"] for r in strategy["categories"] if r["plan"] == "Chase"]
        protect = [r["cat"] for r in strategy["categories"] if r["plan"] in ("Protect", "Hold")]
        if chase or protect:
            parts = []
            if chase:
                parts.append("chase " + ", ".join(chase))
            if protect:
                parts.append("protect " + ", ".join(protect))
            items.append(_item("focus", "This week: " + "; ".join(parts), None, None))

    todo = [i for i in items if i["kind"] in ("lineup", "check", "pickup")]
    return {
        "day": lineup["day"] if lineup else None,
        "is_today": bool(lineup and lineup["is_today"]),
        "lock": lineup["lock"][11:] if lineup and lineup.get("lock") else None,
        "lineup_ok": bool(lineup) and not lineup["swaps"] and not lineup["bench"],
        "win_chance": matchup.get("outlook", {}).get("p_win_matchup"),
        "projected_record": matchup.get("projected_record"),
        "todo_count": len(todo),
        "items": items,
    }


def _item(kind: str, text: str, why: str | None, when: str | None, **extra) -> dict:
    return {"kind": kind, "text": text, "why": why, "when": when, **extra}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
