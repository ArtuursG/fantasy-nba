from fantasy.app import FantasyApp
from fantasy.config import load_config

app = FantasyApp(load_config())
v = app.view()
for r in (v.get("free_agents") or [])[:25]:
    print("FA", r["name"], r["pro_team"], r["health"], r.get("pool_status"), r.get("roster_pct"), r["value"], r["score"], r["games_remaining"], "|", "; ".join(r["reasons"])[:150])
print("BRIEF_START")
print(app.report(brief=True))
