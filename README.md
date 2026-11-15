# fantasy-nba

A daily read of one ESPN head-to-head categories league: this week's
matchup odds, what to pick up and when, the lineup to set, and a report
to paste into ChatGPT. Personal project.

https://artuursg.github.io/fantasy-nba/

## Running it

```
uv run fantasy serve
```

opens the dashboard on this computer. It needs the league and, for a
private league, two ESPN cookies: copy `.dev.vars.example` to `.dev.vars`
and fill it in, or use the Setup tab. `--demo` runs it on an invented
league instead.

| Command | What it does |
|---|---|
| `fantasy serve` | The dashboard, on 127.0.0.1 |
| `fantasy refresh` | Read the league from ESPN and store a snapshot |
| `fantasy report` | The report from the latest snapshot (`--compact`, `--brief`) |
| `fantasy check --notify` | Refresh and send the to-do list to Telegram |
| `fantasy daily` | Refresh and write the report (what the hourly workflow runs) |
| `fantasy backtest` | Replay every stored snapshot and score the forecasts |
| `fantasy export` | The dashboard as static files (`--shell`, `--data`, `--history`) |

## Where things live

- `data/fantasy.db`: every snapshot (one a day once the day is over), the
  forecasts made and the results. Not in the repository.
- `.dev.vars`: league, cookies, Telegram token. Not in the repository.
- The hosted page: `.github/workflows/daily.yml` reads ESPN every hour and
  replaces the `data` branch (`data.json` for the page, `history.db` as a
  copy of the history without the members' ESPN account names);
  `pages.yml` deploys the page itself when its code changes.

## How the numbers are made

- A player's per-game line is his season average, pulled toward ESPN's
  projection while the sample is small and toward the last 15 days once
  there is more (`analysis/stats.py`).
- A matchup's remaining output is each day's best lineup times those
  lines; each category's chance comes from the projected margin and its
  spread (`analysis/matchup.py`).
- The streaming plan, next week's setup and the trade ideas all re-project
  the matchup with a changed roster and keep what adds expected categories
  (`analysis/planner.py`, `nextweek.py`, `trade.py`).
- `fantasy backtest` is the check on all of it: change a number in the
  model, run it, and see whether the forecasts of the weeks already played
  got better.

## Development

```
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```
