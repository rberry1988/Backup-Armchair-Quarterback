# Fantasy Football Copilot

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

It only supports **public** ESPN leagues (no login/cookie flow). If your
league is private, ESPN's data endpoints return 401s.

## Architecture

- `backend/` — FastAPI + SQLite. Pulls league settings/scoring rules,
  teams, rosters, and free agents straight from ESPN's fantasy API
  (undocumented but stable community-known endpoints) and computes
  recommendations server-side.
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

1. Find your league ID in the ESPN URL:
   `fantasy.espn.com/football/league?leagueId=123456` → `123456`.
2. On the **Setup** tab, enter the league ID and season, click **Sync
   League**.
3. Pick your team from the dropdown.
4. Use the **Roster**, **Start / Sit**, **Waivers**, and **Trades** tabs.
   Re-sync any time (e.g. once a week, or after a waiver run) to refresh
   projections — sync fully replaces the previously synced roster/player
   data for that league.

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
- Data storage is a single SQLite file (`backend/data/fantasy.db`) that
  gets wiped and rebuilt from ESPN on every sync — there's no history
  tracked across weeks yet.
