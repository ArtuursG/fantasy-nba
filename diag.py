from fantasy.app import FantasyApp
from fantasy.config import load_config

app = FantasyApp(load_config())
text = app.report(brief=True)
start = text.index("## CATEGORY MAP")
print(text[start : text.index("## MODEL CHECKS")])
start = text.index("## NEXT MATCHUP")
print(text[start : start + 400])
start = text.index("Most rostered")
print(text[start : start + 700])
print("LEN", len(text))
