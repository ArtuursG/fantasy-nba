# fantasy-nba-report

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
REPORT**, and paste the report into ChatGPT. The full report is long (about
120k characters); **Download .md** saves it as a file to attach in ChatGPT
instead of pasting, and **Compact** leaves out the player rankings, the other
teams' rosters and free agents 16-50 (about 60k characters).

The dashboard is split into tabs: **Today** (the matchup scoreboard, tonight's
lineup, changes since yesterday, injuries and acquisitions left), **Matchup**,
**Roster**, **Wire** (free agents and transactions), **League**, **Rankings**,
**Report** (the exact text the copy button puts on the clipboard) and
**Setup**. The fonts ship with the app, so the page loads nothing from the
internet.

The dashboard also has a **Player rankings** table: every rostered player and
free agent with per-game stats and a value for each category, for the full
season, the last 30, 15 or 7 days, or the projection. It filters by free
agents, your team, rostered players or position, and ticking a category under
*Punt* re-ranks everyone without it.

Without the browser:

| Command | Does |
| --- | --- |
| `uv run fantasy refresh` | Reads ESPN and saves a snapshot |
| `uv run fantasy report [--compact] [--out FILE]` | Prints (or writes) the report from the latest snapshot |
| `uv run fantasy daily` | Both, writing `data/reports/<date>.md` |
| `uv run fantasy check [--notify] [--always]` | Refreshes and checks today's lineup; `--notify` sends the alert to Telegram when something needs changing (`--always` sends it anyway) |

Add `--demo` to any command to use an invented league instead of ESPN; it
needs no settings and shows every part of the report with data.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12+).

```bash
cd fantasy-nba-report
uv sync
uv run fantasy serve
```

Open the **Setup** tab of the dashboard and fill in:

- **League or team page URL**: open your team on fantasy.espn.com and copy the
  address from the browser. It carries `leagueId`, `teamId` and `seasonId`, so
  the league, your team and the season all come from it.
- **espn_s2** and **SWID**: two cookies, see below.
- **Punt categories**, if you punt any (for example `TO`).

Saving writes them to `.dev.vars` in this folder (gitignored). The same
settings can be put in that file by hand (`cp .dev.vars.example .dev.vars`);
real environment variables win over it:

| Variable | Value |
| --- | --- |
| `ESPN_LEAGUE_URL` | Any league or team page URL; league, team and season are read from it |
| `ESPN_LEAGUE_ID` | The `leagueId=` number in the league's URL (instead of the URL) |
| `ESPN_SEASON` | Optional. The year the NBA season ends (2026-27 is `2027`); derived from today's date when empty |
| `ESPN_S2`, `ESPN_SWID` | Cookies for a private league, see below |
| `FANTASY_TEAM` | Your team's name, abbreviation or id. Default `Rembates Hektors IR` |
| `FANTASY_PUNT` | Categories you punt, comma-separated (`TO`, `TO,FT%`). Optional |
| `FANTASY_TZ` | Timezone for report times. Default `Europe/Riga` |

ESPN has no API key for fantasy leagues. A private league is read with the
same two cookies the ESPN website uses, which is also how other fantasy tools
connect to ESPN. They come from the browser while logged in to
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

### Lineup alerts before tip-off

Most NBA games tip off at 02:00-04:30 Riga time (earlier on weekends). A check
an hour before catches a starter without a game, a player ruled out late or a
forgotten IR move, and sends it to your phone through Telegram:

1. In Telegram, message **@BotFather**, send `/newbot` and follow the steps;
   it gives you a bot token.
2. Send your new bot any message, then open
   `https://api.telegram.org/bot<token>/getUpdates` in a browser and copy the
   `chat` `id` number.
3. Put both in the dashboard's **Setup** tab (or `TELEGRAM_BOT_TOKEN`
   and `TELEGRAM_CHAT_ID` in `.dev.vars`) and press **Send test alert**.
4. Schedule the check, for example at 18:30 and 01:00:

```bat
schtasks /Create /SC DAILY /ST 01:00 /TN "Fantasy lineup check" /TR "cmd /c cd /d C:\path\to\fantasy-nba-report && uv run fantasy check --notify"
schtasks /Create /SC DAILY /ST 18:30 /TN "Fantasy lineup check (early games)" /TR "cmd /c cd /d C:\path\to\fantasy-nba-report && uv run fantasy check --notify"
```

The alert only comes when there is something to do: who to start and for
whom, who to bench, day-to-day starters to check, IR moves and injuries on
your team since yesterday.

## The report

Same sections in the same order every day:

1. **Header and league rules**: date, league, team, snapshot times, categories, lineup slots, C limit, waiver and acquisition rules, punt strategy.
2. **Today's lineup check**: starts set against the best possible lineup, who to start in whose slot, who to bench, day-to-day starters, IR moves, first tip-off.
3. **My roster**: a table, then per player: positions and slot, health and injury note with expected return, ESPN Player Rater ranks, roster %, season / last 7 / last 15 days per-game lines, value and per-category values, advanced stats (TS%, eFG%, 3P% and 3PA, FTA/FGA, AST/TO, OREB/DREB, stocks, double-double rate, share of team games played), per-36 rates, game-to-game consistency, last 5 games, minutes and starts in the last 5, a usage proxy, role and minutes trend, games this matchup (scheduled, left, usable) and back-to-backs.
4. **Injury / role changes**: minutes up or down, new or lost starting jobs, returns from injury, injured teammates opening minutes, add-rate surges, likely rookies earning a role.
5. **Current matchup**: category score now, projected final with win odds, likely wins, losses and swing categories, expected categories won, the chance of winning the matchup, and what it takes in each category short of a likely win.
6. **Category strategy**: which categories to chase, protect, concede or hold this week, by how much one more streamed game moves each, and the free agents who fit the chase categories.
7. **League transactions**: the last 7 days, marked `[NEW]` since the last report, with waiver results.
8. **Top free agents**: 50, ranked by interest rather than ESPN rank, plus streaming targets.
9. **Add/drop simulator**: the 15 most interesting free agents, each swapped in for the weakest player it helps most to drop, with the effect on usable games, expected categories, matchup win chance and each category.
10. **Streaming plan**: dated adds and drops that spend the acquisitions left, with the gain from each and the category odds before and after.
11. **Opponent roster changes** and the opponent's full roster.
12. **Schedule**: every remaining day with NBA game count, volume, who plays, open starting slots, benched players, and each player's remaining games.
13. **Next matchup preview**: next week's opponent, projected odds per category, games and usable games, each day's volume and open slots.
14. **Acquisitions** used and remaining, and IR status; **waiver order**; **important changes since yesterday**.
15. **Category strength** (projected) and **season category totals** (actual): every team's rank 1-10 in each category.
16. **Trade targets**: players worth more to you than to the league with your punt (buy), yours worth more to others (sell), and help in your weakest categories.
17. **Player rankings** (top 13 rounds), **all team rosters**, **changes vs 7 days ago**, **most rostered free agents**, **forecast accuracy** and **data notes**.

The dashboard shows all of this, plus a filterable player rankings table and a
**trade analyzer**: pick players to give and get and see both teams' category
ranks, the value each side gains and the effect on this week's matchup.

## How the numbers are worked out

- **Projection line** (a player's expected per-game stats): season averages pulled toward ESPN's projection (or last season) while the sample is small, the prior counting as 10 games, then 35% weight on the last 15 days so role changes show early.
- **Usable games**: each remaining day, the roster's healthy players with a game are slotted best-first into PG, SG, SF, PF, C, G, F and 3 UTIL, respecting positions (a bipartite matching); a player who finds no slot is benched and that game is lost. A free agent's usable games are the days he'd find an open slot he can fill on the current roster. IR-slot and OUT players don't count.
- **Matchup projection**: current ESPN category totals plus each starter's projection line for every remaining usable game. Win odds treat the remaining output as random (counting stats over-dispersed Poisson, percentages binomial on the attempts left); 70% or more is a likely win, 30% or less a likely loss. ESPN's matchup data has percentages but not attempts, so attempts so far are estimated from the lineups played.
- **Category strength**: per-game projection totals of each roster's healthy non-IR players, ranked across the league (TO ranked low-is-best).
- **Role trend**: average minutes in the last 5 games against the 10 before (or the season average); 4 or more minutes is UP or DOWN. A starter is someone who started 3 of the last 5. A return from injury is 3 or more missed team games followed by 1-3 games back.
- **Player value**: for each category, a per-game z-score against the rostered players (percentages weighted by attempts, so a high-volume shooter moves FG% more; turnovers count against). A player's value is the average over the categories, about +1 for a first-round player and 0 at the edge of what's rostered. With punt categories set, value averages only the others ("LeagV" keeps all of them), and lineups and free agents are ranked by that value; the matchup section still covers every category.
- **Matchup win chance**: the category odds combined, treating categories as independent, into the odds of each category record; the matchup is won with more categories than the opponent. Categories aren't fully independent (one big night lifts several), so it's a guide, not a promise.
- **Add/drop simulator**: the rest of the matchup re-projected with the pickup in place of the drop, from the day he can play (after the waiver period for a waived player); what was already played is unchanged.
- **Streaming plan**: greedy, one acquisition at a time. Each candidate is tried on his first remaining game day (waived players once they clear) against the three weakest players and the plan's own streamers; the dropped player keeps his games until the day before. The swap adding the most expected categories is kept, until acquisitions run out or no swap adds 0.03. The center limit is respected.
- **Category strategy**: a category's leverage is how much one more game of a typical available streamer moves its win chance; turnovers have negative leverage, since every streamed game adds some.
- **Forecast accuracy**: every refresh records this week's forecast; when a matchup ends its category results are stored, and the forecasts are scored with the Brier score (0 perfect, 0.25 a coin flip) and a calibration table.
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
| `src/fantasy/analysis/` | Schedule and lineups, matchup, roles, free agents, rankings, changes, and `view.py`, which assembles them |
| `src/fantasy/report.py` | The Markdown report |
| `src/fantasy/web/` | Local dashboard (standard library server, one page; fonts under `static/fonts`, SIL Open Font License) |
| `src/fantasy/demo.py` | The invented league used by `--demo` and the tests |
