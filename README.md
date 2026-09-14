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
- **Expert Rankings** (optional, needs a FantasyPros API key) — top-10
  expert consensus rankings, overall and per position, rest-of-season and
  weekly. The Trade Grader also tags any traded player who's in one of
  those top-10 lists with their expert consensus rank and trend.

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

## Deploying to a Proxmox Ubuntu container

`deploy/install.sh` sets this up as a systemd service behind nginx on any
Ubuntu (or Debian-family) machine — an LXC container on Proxmox is exactly
what it's built for. It's been tested end-to-end (real nginx + real systemd
unit + the actual production frontend build, verified by curling through
the proxy) in a container matching this setup.

**1. Create the container in Proxmox**

In the Proxmox web UI: *Create CT* → pick an Ubuntu template (22.04 or
24.04; download one under *local* → *CT Templates* if none is listed yet)
→ give it a couple GB of disk and at least 512MB RAM → finish the wizard
and start it. An unprivileged container is fine; no special Proxmox
features (nesting, KVM passthrough, etc.) are needed since nothing here
runs in Docker — it's plain systemd services.

**2. Clone and install**

Open a shell in the container (Proxmox's *Console*, or SSH once it has an
IP) and run:

```bash
apt-get update && apt-get install -y git
git clone -b claude/fantasy-football-espn-sync-ccv653 \
    https://github.com/rberry1988/Claude.git ~/backup-armchair-quarterback
cd ~/backup-armchair-quarterback
sudo bash deploy/install.sh
```

(That branch name is this project's current home — swap it for `main` once/if this gets merged there.)

The script installs Python/Node/nginx, builds the frontend, generates a
random `JWT_SECRET` into `backend/.env` (only on first run — it won't
overwrite one that already exists), and sets up:

- A systemd service (`backup-armchair-quarterback`) running the backend
  under a dedicated `baq` system user, bound to `127.0.0.1:8000` only.
- An nginx site serving the built frontend on port 80 and reverse-proxying
  `/api/` to the backend — the frontend and API share one origin, so no
  CORS configuration is needed in this setup.

When it finishes it prints the container's IP — open `http://<that-ip>/`
from any browser on your network.

**3. Managing it**

```bash
sudo systemctl status backup-armchair-quarterback   # is it running?
sudo systemctl restart backup-armchair-quarterback  # after editing backend/.env
journalctl -u backup-armchair-quarterback -f        # live logs
```

**To deploy an update:** `git pull` inside the cloned repo, then re-run
`sudo bash deploy/install.sh` — it's safe to re-run; it won't touch your
existing `backend/.env` or the SQLite database, and it restarts the
service with the new code at the end.

**Notes:**

- If `ufw` is enabled in the container, allow HTTP: `sudo ufw allow
  80/tcp`. If the Proxmox host firewall is also enabled for this CT,
  allow port 80 there too.
- This sets up plain HTTP. That's fine on a private/home network; if
  you're exposing it to the public internet, put it behind a domain +
  TLS (e.g. `certbot --nginx` once you have a hostname pointing at it) or
  a VPN (Tailscale/WireGuard) instead of opening port 80 to the world.
- Everything persistent lives in `/opt/backup-armchair-quarterback/backend/data`
  (the SQLite database and the nflverse cache) — back that directory up if
  you'd be sad to lose your synced leagues, and it's the one thing worth
  preserving across a container rebuild.

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

## FantasyPros expert rankings (optional)

Set `FANTASYPROS_API_KEY` in `backend/.env` (get a free key at
[fantasypros.com/api](https://www.fantasypros.com/api/)) to enable the
**Expert Rankings** tab and Trade Grader ECR badges. This is the one
external data source in this app that's a poll of real analysts rather
than a stats computation — everything else here (ESPN, nflverse) is
projection- or history-based.

**The free tier hard-caps every query at the top 10 results**, confirmed
against the live API (not documented by FantasyPros) — `position`,
`player_id`, and `filters` query params don't lift it. That means this
data is only ever useful for elite/startable players:

- The **Expert Rankings** tab shows the top 10 overall and top 10 per
  position, for both rest-of-season and this week.
- The **Trade Grader** tags a traded player with their expert consensus
  rank (e.g. "RB1") and trend arrow *only* when that player happens to be
  in one of those top-10 lists — most trade pieces won't be, and that's
  expected, not a bug.

It will never power full-roster or waiver-wire ECR overlays on this tier;
those players are below the top 10 by definition. A paid FantasyPros API
tier without the cap would make broader integration worth revisiting.

Player IDs are joined via the same dynastyprocess crosswalk used for
nflverse (`fantasypros_id` → `espn_id`); defenses aren't in that crosswalk
so their rankings show up in the tab but can't be tagged onto ESPN D/ST
players elsewhere. Like nflverse, this is entirely best-effort — no key,
or any request failure, just means the feature reports itself as
unavailable rather than breaking sync.

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
