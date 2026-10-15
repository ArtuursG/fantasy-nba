# fantasy

A daily snapshot of an ESPN Fantasy Basketball league, written out as one
structured report to paste into ChatGPT. It collects what a manager needs to
decide on adds, drops, streamers, lineups, trades and category strategy; it
doesn't make those decisions itself.

Built for Wolfy Tribute Federation (10-team H2H categories, 9-cat, analysed
from the side of Rembates Hektors IR), but it reads every setting from ESPN
and works for any head-to-head categories league.

## Daily use

```bash
cd fantasy-nba-report
uv run fantasy serve
```

This opens the dashboard at http://localhost:8765. Press **Refresh** (it reads
the league from ESPN and saves today's snapshot), then **COPY DAILY FANTASY
REPORT**, and paste the report into ChatGPT. **Compact** leaves out the other
teams' full rosters and free agents 16-50 when a shorter paste is wanted (about
40k instead of 70k characters).

Without the browser:

| Command | Does |
| --- | --- |
| `uv run fantasy refresh` | Reads ESPN and saves a snapshot |
| `uv run fantasy report [--compact] [--out FILE]` | Prints (or writes) the report from the latest snapshot |
| `uv run fantasy daily` | Both, writing `data/reports/<date>.md` |

Add `--demo` to any command to use an invented league instead of ESPN; it
needs no settings and shows every part of the report with data.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12+).

```bash
cd fantasy-nba-report
uv sync
cp .dev.vars.example .dev.vars
```

Fill in `.dev.vars` (gitignored; real environment variables win):

| Variable | Value |
| --- | --- |
| `ESPN_LEAGUE_ID` | The `leagueId=` number in the league's URL |
| `ESPN_SEASON` | Optional. The year the NBA season ends (2026-27 is `2027`); derived from today's date when empty |
| `ESPN_S2`, `ESPN_SWID` | Cookies for a private league, see below |
| `FANTASY_TEAM` | Your team's name, abbreviation or id. Default `Rembates Hektors IR` |
| `FANTASY_TZ` | Timezone for report times. Default `Europe/Riga` |

`ESPN_S2` and `ESPN_SWID` come from the browser while logged in to
fantasy.espn.com: open the developer tools (F12), go to Application (Chrome,
Edge) or Storage (Firefox), then Cookies, `https://fantasy.espn.com`, and copy
the values of `espn_s2` and `SWID` (with its curly braces). They last for
months; when Refresh starts failing with HTTP 401, copy them again. They give
read access to your ESPN account, so keep `.dev.vars` private.

### A snapshot every day

History is what makes "changes since yesterday" work, so a snapshot should be
taken every day even when the dashboard isn't opened. On Windows, a scheduled
task does it (adjust the path and time):

```bat
schtasks /Create /SC DAILY /ST 09:00 /TN "Fantasy daily report" /TR "cmd /c cd /d C:\path\to\fantasy-nba-report && uv run fantasy daily"
```

On macOS or Linux, a cron line does the same:

```
0 9 * * * cd /path/to/fantasy-nba-report && uv run fantasy daily
```

## The report

Same sections in the same order every day:

1. **Header and league rules**: date, league, team, snapshot times, categories, lineup slots, C limit, waiver and acquisition rules.
2. **My roster**: a table, then per player: positions and slot, health and injury note with expected return, ESPN Player Rater ranks, roster %, season / last 7 / last 15 days per-game lines, last 5 games, minutes and starts in the last 5, a usage proxy, role and minutes trend, games this matchup (scheduled, left, usable) and back-to-backs.
3. **Injury / role changes**: minutes up or down, new or lost starting jobs, returns from injury (with minutes since return), injured teammates opening minutes, add-rate surges, likely rookies earning a role.
4. **Current matchup**: category score now, projected final with win odds, likely wins, likely losses and swing categories.
5. **League transactions**: the last 7 days, marked `[NEW]` since the last report, with waiver results.
6. **Top free agents**: 50, ranked by interest rather than ESPN rank (15 in detail, 35 in a table), plus streaming targets.
7. **Opponent roster changes** and the opponent's full roster.
8. **Schedule**: every remaining day with NBA game count, low and high volume days, who plays, open starting slots, benched players, and each player's remaining games.
9. **Acquisitions** used and remaining, and IR status.
10. **Waiver order**.
11. **Important changes since yesterday**: the headlines, my team first.
12. **Category strength**: every team's rank 1-10 in each category.
13. **All team rosters**, **changes vs 7 days ago**, **most rostered free agents** and **data notes**.

## How the numbers are worked out

- **Projection line** (a player's expected per-game stats): season averages pulled toward ESPN's projection (or last season) while the sample is small, the prior counting as 10 games, then 35% weight on the last 15 days so role changes show early.
- **Usable games**: each remaining day, the roster's healthy players with a game are slotted best-first into PG, SG, SF, PF, C, G, F and 3 UTIL, respecting positions (a bipartite matching); a player who finds no slot is benched and that game is lost. A free agent's usable games are the days he'd find an open slot he can fill on the current roster. IR-slot and OUT players don't count.
- **Matchup projection**: current ESPN category totals plus each starter's projection line for every remaining usable game. Win odds treat the remaining output as random (counting stats over-dispersed Poisson, percentages binomial on the attempts left); 70% or more is a likely win, 30% or less a likely loss. ESPN's matchup data has percentages but not attempts, so attempts so far are estimated from the lineups played.
- **Category strength**: per-game projection totals of each roster's healthy non-IR players, ranked across the league (TO ranked low-is-best).
- **Role trend**: average minutes in the last 5 games against the 10 before (or the season average); 4 or more minutes is UP or DOWN. A starter is someone who started 3 of the last 5. A return from injury is 3 or more missed team games followed by 1-3 games back.
- **Free-agent interest**: a 9-cat z-score of the projection line, plus recent form, minutes trend, a new starting job, an injured teammate at his position, a return from injury, the add rate and usable games, minus a penalty while he's out.

## History

Every refresh is stored as one row in `data/fantasy.db` (SQLite, gitignored):
the whole normalised snapshot, compressed. "Since yesterday" compares with the
last snapshot from an earlier day, so refreshing several times a day still
compares with yesterday; the 7-day view uses the latest snapshot at least a
week old. Changes tracked: roster moves, injury status, minutes, starting
roles and roster %.

## Limits

- ESPN's fantasy API is unofficial and undocumented. The client uses the
  endpoints, views and filters of the open-source
  [espn-api](https://github.com/cwendt94/espn-api) library and the ESPN
  website. If a refresh
  fails or a section comes out empty after an ESPN change, run
  `uv run fantasy refresh --save-raw data/raw` and inspect (or share) the
  saved responses; they contain league data but not your cookies.
- ESPN publishes no usage rate; the report shows a usage proxy, (FGA + 0.44
  FTA + TO) per 36 minutes, instead.
- ESPN's recent splits are 7, 15 and 30 days, so "last 14 days" is reported as
  ESPN's last 15.
- ESPN doesn't say when a waived player clears; the time shown is the drop
  time plus the waiver period, marked "est.".
- Injury descriptions come from ESPN's public NBA injury report, which only
  lists currently injured players.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

CI runs the same on every push. The tests run the whole pipeline (ESPN
client against a fake ESPN, parser, analysis, report, CLI and web server) on
the invented demo league.

## Layout

| Path | Contents |
| --- | --- |
| `src/fantasy/espn/` | ESPN client (`fetch_bundle`) and parser into a snapshot |
| `src/fantasy/models.py` | The normalised snapshot |
| `src/fantasy/store.py` | Snapshot history in SQLite |
| `src/fantasy/analysis/` | Schedule and lineups, matchup, roles, free agents, changes, and `view.py`, which assembles them |
| `src/fantasy/report.py` | The Markdown report |
| `src/fantasy/web/` | Local dashboard (standard library server, one page) |
| `src/fantasy/demo.py` | The invented league used by `--demo` and the tests |
