# Backup Armchair Quarterback

A local web app that syncs your ESPN fantasy football league (rosters,
teams, and scoring rules) and gives you three things every week:

- **Start / Sit** — an optimal-lineup check that flags any bench player
  projected to outscore a current starter at an eligible slot, and calls
  out injured/bye-week starters.
- **Waiver Wire** — free agents projected to outscore your weakest rostered
  player at the same position, with a suggested drop.
- **Trade Analysis** — your team's weak positions vs. league median, your
  deepest bench positions (trade chips), and other teams whose needs and
  surplus complement yours.
- **Trade Grader** — pick players either side of a trade would send and get
  a fairness verdict + letter grade per team, using each player's
  rest-of-season average projected points (not just this week's number) and
  a note when the trade addresses a team's positional need.
- **Matchup difficulty** — Start/Sit and Waivers both tag each player with
  their opponent this week and a tough/average/favorable label, based on
  real points-allowed-by-position data where available (see nflverse
  below), and **suggested FAAB bids** on waiver adds.
- **Usage trends** — Roster and Waivers show each player's last few played
  weeks of targets, carries, receptions, or pass attempts, plus (when
  available) real target share and snap % from nflverse — an up/down/flat
  label on whichever's most relevant to their position, since these
  opportunity shifts tend to move before fantasy points do.

It only supports **public** ESPN leagues (no ESPN login/cookie flow). If
your league is private, ESPN's data endpoints return 401s.

Multiple people can use the same instance: each person registers their own
account and their synced league(s), team selection, and recommendations
are private to them, even if two people happen to sync the same ESPN
league.

## Architecture

- `backend/` — FastAPI + SQLite. Handles user accounts (email/password,
  JWT sessions) and, per user, pulls league settings/scoring rules,
  teams, rosters, and free agents straight from ESPN's fantasy API
  (undocumented but stable community-known endpoints) and computes
  recommendations server-side. Enriches that with
  [nflverse](https://github.com/nflverse/nflverse-data) — free,
  open-source NFL play-by-play data — for stats ESPN's API doesn't expose
  (target share, air yards share, WOPR, snap %) and for computing real
  points-allowed-by-position defense ratings.
- `frontend/` — Vite + React + TypeScript single-page app.

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional, defaults work for most public leagues
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # optional, defaults to http://localhost:8000
npm run dev
```

Open http://localhost:5173.

## Using it

1. Register an account on the login screen (just an email + password —
   this is a local account, unrelated to your ESPN login).
2. Find your league ID in the ESPN URL:
   `fantasy.espn.com/football/league?leagueId=123456` → `123456`.
3. On the **Setup** tab, enter the league ID and season, click **Sync
   League**.
4. Pick your team from the dropdown.
5. Use the **Roster**, **Start / Sit**, **Waivers**, **Trades**, and
   **Trade Grader** tabs. Re-sync any time (e.g. once a week, or after a
   waiver run) to refresh projections and pull in the new week's stats —
   each sync adds to a running per-week history rather than throwing away
   past weeks, which is what the Trade Grader's rest-of-season values are
   built from.

Each teammate in your league can register their own account on the same
running instance and pick their own team — nobody sees anyone else's
selections or synced data.

## Notes and limitations

- Projected/actual points come straight from ESPN's own per-league
  `appliedTotal` on each player's stat entry, which ESPN already computes
  using your league's synced scoring settings (custom PPR, TD points,
  etc.) — no need to re-derive fantasy points from raw stat counts.
- ESPN's API is undocumented and can change its response shape without
  notice. If sync starts failing or a screen looks empty/wrong, the most
  likely cause is a shifted field name in `backend/app/scoring.py` or
  `backend/app/sync_service.py` — those are the two files that parse
  ESPN's raw JSON.
- The trade/waiver/start-sit logic is heuristic decision support, not a
  guarantee — it's meant to surface things worth a second look, not to be
  blindly followed.
- Data storage is a single SQLite file (`backend/data/fantasy.db`). Team
  rosters and free agents are wiped and rebuilt from ESPN on every sync
  (they only reflect "right now"), but per-week player stat snapshots
  accumulate across syncs — that history powers rest-of-season averages
  like the Trade Grader's player values.
- The trade grader's letter grades are a simple heuristic (percentage
  value gap between the two sides), the same kind of arbitrary-but-useful
  scale sites like FantasyPros use — treat it as a sanity check, not a
  verdict.
- Login sessions are JWTs signed with `JWT_SECRET` (set in `backend/.env`).
  Change it from the placeholder before letting anyone other than you use
  the app — anyone who knows the secret can forge a session for any user
  id. Sessions last 2 weeks by default (`JWT_EXPIRE_MINUTES`).
- Matchup difficulty prefers real average PPR points-allowed-per-game by
  position (computed from nflverse's weekly stats, using only games played
  so far this season), ranked league-wide — fewer points allowed by a
  defense means a tougher matchup for the offense facing it. If that data
  isn't available for a team/position (nflverse unreachable, or too early
  in the season), it falls back to a cruder proxy: the opponent's own
  projected D/ST fantasy score. The `matchup.source` field on API
  responses says which one was used (`points_allowed` or
  `dst_projection`). The NFL schedule itself comes from ESPN's separate
  public scoreboard API (not the fantasy API); if that's unreachable at
  sync time, matchup tags just don't appear rather than breaking the sync.
- Suggested FAAB bids are a simple heuristic (scaled off the point upgrade
  a pickup projects over your weakest rostered player at that position, as
  a % of a 100-point budget) — not read from your league's actual FAAB
  budget or waiver settings. Ignore them if your league uses waiver
  priority instead of FAAB.
- Usage trends combine ESPN's raw per-week counting stats (pass
  attempts/completions/yards, carries/rush yards, targets/receptions/rec
  yards) with nflverse's advanced metrics (target share, snap %) where a
  player has a crosswalk match. The trend label compares the first half of
  the last 4 played weeks to the second half; it needs at least 2 played
  weeks of history to show anything; K and D/ST don't have a meaningful
  stat here and are skipped.
- Schema changes to `PlayerWeekStat`/`League` (adding the usage/advanced-
  stats and points-allowed columns) only apply to a freshly created
  database — if you're upgrading an existing `backend/data/fantasy.db`
  from before these features, delete it and re-sync your league(s) rather
  than expecting new columns to appear on their own (there's no migration
  framework in this app).

## nflverse data (advanced stats + real matchup ratings)

`backend/app/nflverse_client.py` pulls three free, public CSVs, no API key
needed:

- A player-id crosswalk (maintained by the
  [dynastyprocess](https://github.com/dynastyprocess/data) project) to map
  ESPN's player ids to the `gsis_id`/`pfr_id` nflverse and Pro-Football-
  Reference use — the two ecosystems don't share an id scheme.
- nflverse's combined weekly player stats file (all seasons since 1999 in
  one ~33MB CSV) — target share, air yards share, WOPR, and raw
  yardage/target/carry counts, filtered down to the current season while
  parsing.
- nflverse's per-season snap-count file, for offensive snap %.

Downloads are cached to `backend/data/nflverse_cache/` for 6 hours, so
only the first sync in a while pays the download/parse cost (a few
seconds); everything after that reads from disk. All of it is best-effort
— if nflverse is unreachable or a player has no crosswalk match, sync
still completes normally and that player's advanced stats/points-allowed
data are simply absent that time.
