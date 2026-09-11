# Over 2.5 Predictor

A personal research tool that scans football fixtures worldwide for the next
7 days, pulls team/league stats, runs a 15-point checklist against each
fixture, and emails you a ranked CSV. **It does not place bets** — it only
surfaces candidate matches with supporting data for you to review yourself.

## How it works

1. `fixtures.py` fetches all not-yet-started fixtures for each of the next
   `LOOKAHEAD_DAYS` days (default 7), across all leagues, via the
   [API-Football](https://www.api-football.com/) v3 API.
2. `team_stats.py` fetches season stats, standings, recent form, and
   (best-effort) xG/injuries for each team involved.
3. `checks.py` runs the 15-point checklist (below) against every fixture.
4. `scoring.py` scores each fixture (`checks_passed` / `checks_computable`)
   and writes a ranked CSV.
5. `emailer.py` emails the CSV to you via Gmail SMTP.
6. `over25_predictor.py` is the entry point that wires all of the above
   together and logs each run to `over25_predictor.log`.

## Setup

1. **Install Python 3.10+** on the Windows machine that will run this.
2. Open a terminal in this folder and install dependencies:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Get an API-Football key.**
   - Sign up at [api-football.com](https://www.api-football.com/) (direct
     account) or subscribe via [RapidAPI](https://rapidapi.com/api-sports/api/api-football).
   - The free tier is rate-limited (typically 100 requests/day on the direct
     free plan) — see **API usage & quota** below, this matters a lot for
     worldwide scans.
4. **Generate a Gmail app password** (not your normal Google password):
   [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   (requires 2-Step Verification enabled on the account).
5. Copy `.env.example` to `.env` and fill in:
   - `API_FOOTBALL_KEY`, `API_PROVIDER` (`direct` or `rapidapi`)
   - `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
   - `OUTPUT_DIR` (defaults to `C:\Users\kdalt\Desktop\Football Bets`)
   - Leave `LEAGUE_WHITELIST=Premier League` for the first dry run (step 6).

   `.env` is gitignored — never commit it.
6. **Dry run on Premier League only first**, to sanity-check the numbers
   before scaling up API usage:
   ```
   python over25_predictor.py --leagues "Premier League" --no-email
   ```
   Check the CSV in `OUTPUT_DIR` against what you'd expect for those
   fixtures, then remove `LEAGUE_WHITELIST` in `.env` (or drop `--leagues`)
   to go worldwide, and drop `--no-email` to start emailing.
7. Double-click `run_over25_predictor.bat` to run manually any time.
8. Register the daily scheduled task (see below).

## The 15-point checklist

Checks 1–13 are scored (shown as `checks_passed` out of `checks_computable`
in the CSV — a match with data gaps isn't unfairly penalised for checks that
simply couldn't be computed). Checks 14–15 are informational flags, not part
of the score.

| # | Check | Column |
|---|-------|--------|
| 1 | Both teams have played 5+ games this season (gate — fixture excluded entirely if failed) | `check_1` |
| 2 | Each team's BTTS rate this season > 60% | `check_2` |
| 3 | Each team's clean sheet rate < 35% | `check_3` |
| 4 | Combined goals/game (home GPG + away GPG) > 3.5 | `check_4` |
| 5 | Home team 5+ places higher in the table | `check_5` |
| 6 | Both teams average > 4 shots on target/game | `check_6` |
| 7 | Home GF avg > 3 **and** away GA avg > 3 | `check_7` |
| 8 | Combined expected goals estimate > 2.5 (**approximation**, see below) | `check_8` |
| 9 | Last 3 head-to-head meetings all over 2.5 goals | `check_9` |
| 10 | 60%+ of each team's last 5 games were over 2.5 goals | `check_10` |
| 11 | Each team's GPG > their league's average GPG | `check_11` |
| 12 | Each team scores in the first 15 min in 40%+ of games (last `TIMING_LOOKBACK_GAMES`) | `check_12` |
| 13 | Each team scores in the last 15 min in 40%+ of games | `check_13` |
| 14 | Key players (GK/defenders/top scorers) confirmed out — flag only | `key_players_missing` |
| 15 | Cup/relegation/dead-rubber context — free text, only what's derivable | `context_notes` |

Each `check_N` cell is `TRUE`, `FALSE`, or `N/A` (not computable). The
`data_gaps` column explains *why* anything is `N/A` for that row.

## Known data limitations — read this before trusting a "N/A"

API-Football doesn't cleanly map onto all 15 checks. Rather than guess, this
tool marks a check `N/A` and explains why in `data_gaps`:

- **Checks 12/13 (early/late goals)** need the fixture-events endpoint for
  *every* historical match in the lookback window — one API call per match
  per team. `TIMING_LOOKBACK_GAMES` (default 10) caps this; a smaller number
  saves quota but gives a noisier rate. If fewer than `MIN_TIMING_SAMPLE`
  matches have usable event data, the check comes back `N/A` for that team
  rather than computed on a tiny/unreliable sample.
- **Check 8 (xG)** is only exposed by API-Football as a fixture statistic
  for a subset of top leagues/seasons. Where it's missing, `check_8` is
  `N/A` — it is never estimated from goals scored or anything else. Where
  it *is* available, the "combined expected goals" figure is our own
  approximation (`(home xG-for + home xGA + away xG-for + away xGA) / 2`,
  averaged over the team's recent matches) since the checklist's exact
  intended formula isn't a single API field — see `checks.py::check_8_expected_goals`.
- **Check 14 (injuries)** uses the `/injuries` endpoint, which isn't
  populated for every league. `key_players_missing` is literally the string
  `"Unknown"` when the data isn't available for either team — never assumed
  to mean "no injuries".
- **Check 15 (context)** only states what's derivable: competition type
  (cup vs league) and relegation-zone position from standings. It does not
  attempt to infer "dead rubber" (nothing decided) or other narrative
  context that isn't in the data — `context_notes` is left blank if nothing
  derivable applies.
- **Any check** can come back `N/A` for an individual fixture even outside
  these categories (e.g. a newly promoted team with too few historical
  matches for `check_10`). This is expected and shown, not hidden.

## API usage & quota

A worldwide 7-day scan can involve a *lot* of calls:
- 7 calls for fixture lists (one per day)
- 1 team-statistics + 1 standings + 1 fixtures(last=N) + 1 H2H call per team
  per fixture (deduplicated within a run if a team appears twice)
- Up to `TIMING_LOOKBACK_GAMES` **extra** calls per team for match events
  (checks 12/13), and again for fixture statistics if `FETCH_XG=true`

On a free-tier plan (commonly ~100 requests/day) this will exceed quota
fast once you go past a handful of leagues. Options, in order of impact:
- Use `LEAGUE_WHITELIST` to restrict to the leagues you actually care about.
- Lower `TIMING_LOOKBACK_GAMES` (fewer matches -> fewer event-endpoint calls).
- Set `FETCH_XG=false` (xG is unavailable for most leagues anyway).
- Raise `CACHE_TTL_HOURS` (responses are cached to disk in `cache/` — the
  same team/league won't be re-fetched within the TTL window even across
  separate runs the same day).

The email summary and log line at the end of every run report
`API calls made this run` and `cache hits` so you can see exactly where
quota is going and tune from there.

## Running manually

```
run_over25_predictor.bat
```
or
```
python over25_predictor.py --leagues "Premier League" --no-email
```

## Scheduling (Windows Task Scheduler)

**Recommended time: 07:00 UK time**, daily — early enough to be useful
before most kick-offs, late enough to reflect overnight news for at least
some of that day's/coming week's team updates (lineup/injury news for
specific games still won't be final until much closer to kick-off — see
limitations above).

### Option A — script (recommended)
From an **elevated** PowerShell prompt, in this folder:
```
powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1
```
This registers a task called "Over 2.5 Predictor" that runs
`run_over25_predictor.bat` daily at 07:00. Edit `$TaskTime` in the script
first if you want a different time.

### Option B — manual GUI steps
1. Open **Task Scheduler** → **Create Task…** (not "Create Basic Task", so
   you get the full options).
2. **General** tab: name it "Over 2.5 Predictor"; select "Run whether user
   is logged on or not" if you want it to run even when locked.
3. **Triggers** tab → **New…** → Daily, start time 07:00, recur every 1 day.
4. **Actions** tab → **New…** → Action "Start a program", Program/script:
   the full path to `run_over25_predictor.bat`, Start in: this folder's path.
5. **Settings** tab: tick "Run task as soon as possible after a scheduled
   start is missed" (useful if the PC was off at 07:00).
6. Save, then right-click the task → **Run** to test it immediately.

## Logs

Every run appends to `over25_predictor.log` in this folder (rotated at
~2MB, 5 backups kept) — timestamp, fixtures scanned, matches scored,
API call/cache counts, and any errors. Check this first if a scheduled run
didn't produce a CSV or email.

## Project layout

```
over25-predictor/
  over25_predictor.py       entry point
  config.py                 loads .env / config.json
  api_client.py              API-Football HTTP client (cache + rate limit)
  fixtures.py                 fixture-fetching layer
  team_stats.py                per-team stats layer (standings, form, xG, injuries)
  checks.py                    the 15-point checklist
  scoring.py                    CSV row building + writing
  emailer.py                    Gmail SMTP sender
  logger_setup.py                logging config
  run_over25_predictor.bat  manual/scheduled runner
  setup_task_scheduler.ps1  registers the daily Task Scheduler job
  tests/test_checks.py      offline sanity tests for the checklist logic (no API key needed)
  .env.example               copy to .env and fill in your keys (gitignored)
```
