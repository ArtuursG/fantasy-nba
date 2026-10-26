import json
from pathlib import Path

from fantasy.app import FantasyApp
from fantasy.config import load_config

raw = json.loads(sorted(Path("raw").glob("*.json"))[-1].read_text())
lg = raw["league"]
print("SP", lg.get("scoringPeriodId"), "status", json.dumps({k: lg.get("status", {}).get(k) for k in ("currentMatchupPeriod", "firstScoringPeriod", "latestScoringPeriod")}))
sched = (lg.get("settings") or {}).get("scheduleSettings") or {}
print("DIVISIONS", json.dumps(sched.get("divisions")))
print("PLAYOFF", json.dumps({k: sched.get(k) for k in ("playoffTeamCount", "playoffSeedingRule", "playoffSeedingRuleBy", "divisions")}, default=str)[:600])
for t in lg.get("teams", []):
    keep = {k: t.get(k) for k in ("id", "abbrev", "divisionId", "playoffSeed", "rankCalculatedFinal", "currentProjectedRank", "rankFinal", "points", "waiverRank")}
    keep["record"] = {k: (t.get("record") or {}).get(k) for k in ("overall", "division")}
    keep["valuesByStat"] = t.get("valuesByStat")
    print("TEAM", json.dumps(keep))
app = FantasyApp(load_config())
v = app.view()
print("STANDINGS", json.dumps(v.get("season_standings")))
for r in (v.get("free_agents") or [])[:30]:
    print("FA", json.dumps({k: r.get(k) for k in ("name", "pro_team", "health", "pool", "waiver_until", "roster_pct", "value", "score", "games_remaining", "usable_remaining", "reasons")}))
print("FAKEYS", list((v.get("free_agents") or [{}])[0].keys()))
fa = raw["free_agents"].get("players") or []
for w in fa[:30]:
    p = w.get("player") or {}
    print("ESPNFA", w.get("id"), p.get("fullName"), w.get("status"), p.get("injuryStatus"), (p.get("ownership") or {}).get("percentOwned"))
print("BRIEF_START")
print(app.report(brief=True))
