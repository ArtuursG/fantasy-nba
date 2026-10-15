"""What changed between two snapshots: roster moves, injuries, minutes,
starting roles and ownership, plus a prioritised list of headlines."""

from __future__ import annotations

from statistics import fmean

from fantasy.analysis.context import Context
from fantasy.analysis.stats import last_games
from fantasy.espn.constants import HEALTH_LABELS, UNAVAILABLE_STATUSES
from fantasy.models import Player, Snapshot

MINUTES_CHANGE = 4.0


def _minutes_and_starts(player: Player) -> tuple[float, int, int] | None:
    games = last_games(player, 5)
    if len(games) < 3:
        return None
    return fmean(g.line.min for g in games), sum(1 for g in games if g.started), len(games)


def _health(status: str) -> str:
    return HEALTH_LABELS.get(status, status)


def compare(ctx: Context, prev: Snapshot | None, ownership_step: float = 5.0) -> dict:
    """Changes from `prev` to the context's snapshot (empty without `prev`)."""
    result: dict = {
        "since": prev.fetched_at if prev else None,
        "roster_moves": [],
        "injuries": [],
        "minutes": [],
        "starters": [],
        "ownership": [],
        "bullets": [],
    }
    if prev is None:
        return result
    snap = ctx.snap
    opp_id = ctx.opponent_id(snap.my_team_id)

    def name(player_id: int) -> str:
        player = snap.players.get(player_id) or prev.players.get(player_id)
        return player.name if player else f"Player {player_id}"

    before = {t.id: {s.player_id for s in t.roster} for t in prev.teams}
    for team in snap.teams:
        now = {s.player_id for s in team.roster}
        added, dropped = now - before.get(team.id, set()), before.get(team.id, set()) - now
        if added or dropped:
            result["roster_moves"].append(
                {
                    "team_id": team.id,
                    "team": team.name,
                    "is_me": team.id == snap.my_team_id,
                    "is_opp": team.id == opp_id,
                    "added": sorted(name(p) for p in added),
                    "dropped": sorted(name(p) for p in dropped),
                }
            )

    tracked = {s.player_id for t in snap.teams for s in t.roster} | set(snap.free_agent_ids)
    for player_id in sorted(tracked):
        player, old = snap.players.get(player_id), prev.players.get(player_id)
        if player is None or old is None:
            continue
        owner = ctx.owner_label(player)
        if old.injury_status != player.injury_status:
            result["injuries"].append(
                {
                    "player_id": player_id,
                    "name": player.name,
                    "owner": owner,
                    "from": _health(old.injury_status),
                    "to": _health(player.injury_status),
                    "worse": player.injury_status in UNAVAILABLE_STATUSES,
                    "note": player.injury_note,
                }
            )
        now_ms, old_ms = _minutes_and_starts(player), _minutes_and_starts(old)
        if now_ms and old_ms:
            if abs(now_ms[0] - old_ms[0]) >= MINUTES_CHANGE:
                result["minutes"].append(
                    {
                        "player_id": player_id,
                        "name": player.name,
                        "owner": owner,
                        "from": old_ms[0],
                        "to": now_ms[0],
                    }
                )
            if now_ms[1] >= 3 and old_ms[1] <= 1:
                change = "promoted to starter"
            elif now_ms[1] <= 1 and old_ms[1] >= 3:
                change = "moved to the bench"
            else:
                change = None
            if change:
                result["starters"].append(
                    {
                        "player_id": player_id,
                        "name": player.name,
                        "owner": owner,
                        "change": change,
                        "from": old_ms[1],
                        "to": now_ms[1],
                        "games": now_ms[2],
                    }
                )
        if player.percent_owned is not None and old.percent_owned is not None:
            delta = player.percent_owned - old.percent_owned
            if abs(delta) >= ownership_step:
                result["ownership"].append(
                    {
                        "player_id": player_id,
                        "name": player.name,
                        "owner": owner,
                        "from": old.percent_owned,
                        "to": player.percent_owned,
                        "delta": delta,
                    }
                )
    result["ownership"].sort(key=lambda r: -abs(r["delta"]))
    result["bullets"] = _bullets(result, ctx)
    return result


def owner_phrase(owner: str) -> str:
    if owner == "MY TEAM":
        return "your team"
    if owner.startswith("OPPONENT (") and owner.endswith(")"):
        return "opponent " + owner[len("OPPONENT (") : -1]
    if owner in ("FA", "WA"):
        return "free agent" if owner == "FA" else "on waivers"
    return owner


def _priority(owner: str) -> int:
    if owner == "MY TEAM":
        return 0
    if owner.startswith("OPPONENT"):
        return 1
    if owner in ("FA", "WA"):
        return 3
    return 2


def _bullets(changes: dict, ctx: Context) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for item in changes["injuries"]:
        owner = item["owner"]
        text = f"{item['name']} ({owner_phrase(owner)}) injury: {item['from']} -> {item['to']}"
        ranked.append((_priority(owner), 0 if item["worse"] else 1, text))
    for move in changes["roster_moves"]:
        parts = []
        if move["added"]:
            parts.append("added " + ", ".join(move["added"]))
        if move["dropped"]:
            parts.append("dropped " + ", ".join(move["dropped"]))
        who = (
            "You"
            if move["is_me"]
            else f"Opponent {move['team']}"
            if move["is_opp"]
            else move["team"]
        )
        priority = 0 if move["is_me"] else 1 if move["is_opp"] else 2
        ranked.append((priority, 2, f"{who} {' and '.join(parts)}"))
    for item in changes["starters"]:
        text = (
            f"{item['name']} ({owner_phrase(item['owner'])}) {item['change']}: started "
            f"{item['to']} of last {item['games']} (was {item['from']})"
        )
        ranked.append((_priority(item["owner"]), 3, text))
    for item in changes["minutes"]:
        verb = "increased" if item["to"] > item["from"] else "decreased"
        text = (
            f"{item['name']} ({owner_phrase(item['owner'])}) minutes {verb} from "
            f"{item['from']:.0f} to {item['to']:.0f} (last-5 average)"
        )
        ranked.append((_priority(item["owner"]), 4, text))
    for item in changes["ownership"][:8]:
        text = (
            f"{item['name']} ({owner_phrase(item['owner'])}) rostered {item['from']:.1f}% -> "
            f"{item['to']:.1f}% of ESPN leagues"
        )
        ranked.append((_priority(item["owner"]) + 1, 5, text))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [text for _, _, text in ranked]
