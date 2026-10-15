"""Telegram alerts: a short message when the lineup needs attention."""

from __future__ import annotations

import httpx

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE = 4000


class NotifyError(Exception):
    pass


def send_telegram(
    token: str, chat_id: str, text: str, transport: httpx.BaseTransport | None = None
) -> None:
    with httpx.Client(timeout=20, transport=transport) as client:
        try:
            response = client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:MAX_MESSAGE],
                    "disable_web_page_preview": True,
                },
            )
        except httpx.TransportError as exc:
            raise NotifyError(f"Could not reach Telegram: {exc}") from exc
    if response.status_code != 200:
        detail = response.json().get("description", "") if response.content else ""
        raise NotifyError(f"Telegram refused the message (HTTP {response.status_code}) {detail}")


def alert_text(view: dict, always: bool = False) -> str | None:
    """The alert for a view, or None when there's nothing to act on."""
    check = view.get("lineup")
    lines: list[str] = []
    if check:
        when = "today" if check["is_today"] else check["day"]
        if check["lost_games"]:
            lines.append(
                f"Lineup {when}: {check['current_starts']} of {check['best_starts']} possible "
                f"starts set, {check['lost_games']} game(s) lost unless you change it."
            )
        for swap in check["swaps"]:
            tip = f" (tip-off {swap['tipoff']})" if swap["tipoff"] else ""
            if swap["for"]:
                lines.append(
                    f"Start {swap['start']}{tip} in {swap['slot']} for {swap['for']} "
                    f"({swap['reason']})"
                )
            else:
                lines.append(f"Start {swap['start']}{tip}: rearrange the slots to fit him")
        for item in check["bench"]:
            lines.append(f"Bench {item['name']} ({item['reason']})")
        lines += [f"Check before lock: {w}" for w in check["watch"]]
        lines += check["ir"]
    injuries = [
        i for i in (view.get("changes") or {}).get("injuries", []) if i["owner"] == "MY TEAM"
    ]
    lines += [f"Injury: {i['name']} {i['from']} -> {i['to']}" for i in injuries]
    if not lines and not always:
        return None
    header = f"{view['meta']['my_team'] or 'Fantasy'}: "
    if check and check["lock"]:
        header += f"first lock {check['lock'][11:]}"
    mu = view.get("matchup")
    if mu:
        header += (
            f" | matchup win {mu['outlook']['p_win_matchup'] * 100:.0f}%,"
            f" {mu['outlook']['expected_wins']:.1f} cats expected"
        )
    return "\n".join([header, *(lines or ["Lineup is set; nothing to change."])])
