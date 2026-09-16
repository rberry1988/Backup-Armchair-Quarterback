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
  below), and **suggested FAAB bids** on waiver adds. Start/Sit shows the
  numbers behind each label rather than asking you to take it on faith,
  in the units the position is actually judged in — rushing yards allowed
  for RBs, receiving yards for WRs and TEs, passing yards for QBs, with
  the league average and the rank alongside. Explaining a points
  projection with points allowed would be circular; yardage is the thing
  underneath it. K and D/ST have no such stat, so they still rate on
  fantasy points allowed and say so.
- **Usage trends** — Roster and Waivers show each player's last few played
  weeks of targets, carries, receptions, or pass attempts, plus (when
  available) real target share and snap % from nflverse — an up/down/flat
  label on whichever's most relevant to their position, since these
  opportunity shifts tend to move before fantasy points do.
- **Expert Rankings** (optional, needs a FantasyPros API key) — top-10
  expert consensus rankings, overall and per position, rest-of-season and
  weekly. The Trade Grader also tags any traded player who's in one of
  those top-10 lists with their expert consensus rank and trend.
- **Depth Charts** — an inferred (not official) depth chart per NFL team
  and position, ranked by nflverse snap % where available and ESPN's
  percent-started/projected points otherwise, showing whether each player
  is a free agent, on your roster, or rostered by another team.
- **RB Handcuffs** — for each running back on your roster, the next back
  on their NFL team per the depth chart above, flagged if that handcuff is
  sitting on waivers.
- **Alerts** — the landing tab: every injured or bye-week player in your
  lineup, paired with who'd absorb their role on their NFL team and the
  best replacements actually available on your waiver wire. Below it, a
  **what changed since your last sync** digest — injury flips, roster moves
  across the league, ownership spikes, and projection swings.
- **Schedule** — a bye-week planner that flags weeks where enough players
  at one position are off to leave a starting slot uncoverable, plus a
  multi-week matchup outlook (next four weeks and the fantasy playoff
  weeks) rated the same way as the current week's matchup tags.
- **Floor / ceiling** — Roster tags each player steady, streaky, or
  boom/bust from their own weekly scoring history, with the floor and
  ceiling they've actually posted.
- **Bench Points** — every past week's real starting lineup scored against
  the best lineup that same roster could have fielded, with the specific
  swaps you missed and a season running total.
- **Pending Moves** (premium, needs a connected ESPN account) — on the
  Waivers tab, the waiver claims,
  free-agent adds and trade offers you have genuinely submitted in ESPN and
  that ESPN hasn't processed yet, read live from ESPN. Needs your own ESPN
  account connected (see below). Read-only: this app never submits or
  cancels a claim for you, and **Refresh** re-checks ESPN on the spot.
  Underneath it sits your own local shortlist, built with the **Plan**
  button on any waiver recommendation.

Public ESPN leagues work with no setup at all. For a **private** league,
or for real pending claims, connect your own ESPN account under
**Settings → Account** — a premium-only section, since what it unlocks is
a premium panel (the section is hidden for basic accounts, and its
endpoints refuse them). That page has a **Get ESPN cookies** bookmarklet:
drag it to your bookmarks bar, click it once while signed in on
fantasy.espn.com, and it copies your `espn_s2` and `SWID` to the
clipboard — paste that back into the app and hit Connect. (Pasting a whole
cookie dump works too; only those two values are picked out, in your
browser, and only those two are sent to the server. There's a manual
two-field fallback under "Enter them separately instead" if you'd rather
copy them out of devtools.)

A browser can't hand cookies from espn.com to another site on its own —
that's the same-origin policy, and no app code gets around it — so the
bookmarklet is the shortest honest path: it runs on ESPN's own page,
reads two cookies, and sends them nowhere.

Works in any Chromium browser (Chrome, Edge, Brave) and Firefox. Two
things worth knowing:

- If the browser refuses the clipboard write — some do, for a script
  started from a bookmark — a box pops up with the text instead. Copy it
  from there; nothing is lost.
- Brave's "Forget me when I close this site" (Shields → advanced) clears
  espn.com's cookies when you close the tab, which logs out the session
  this depends on. Leave it off for espn.com, or expect to re-run the
  bookmarklet often.

Those cookies are stored per account, used only to serve your own
requests, and never sent back to any browser once saved. ESPN expires them
every few weeks, so re-run the bookmarklet when claims stop showing up.

Multiple people can use the same instance: each person registers their own
account and their synced league(s), team selection, and recommendations
are private to them, even if two people happen to sync the same ESPN
league.

If you'd rather add your teammates yourself instead of everyone
self-registering, set `ADMIN_EMAILS` (see below) to get an **Admin** tab
for adding and removing accounts.

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

The script clones this repo directly into `/opt/backup-armchair-quarterback`
(not a copy — an independent git checkout, which is what lets the Admin
tab's Update button pull its own updates later), installs Python/Node/nginx,
builds the frontend, generates a random `JWT_SECRET` and a default admin
account into `backend/.env` (only on first run — it won't overwrite either
if they already exist), and sets up:

- A systemd service (`backup-armchair-quarterback`) running the backend
  under a dedicated `baq` system user, bound to `127.0.0.1:8000` only.
- An nginx site serving the built frontend on port 80 and reverse-proxying
  `/api/` to the backend — the frontend and API share one origin, so no
  CORS configuration is needed in this setup.

When it finishes it prints the container's IP and a one-time admin login
— open `http://<that-ip>/` from any browser on your network and sign in
with those, e.g.:

```
    App:     http://192.168.1.50/
    ...
    Log in at http://192.168.1.50/ with:
      Email:    admin@example.com
      Password: aB3dEfGh9k
    This is shown once — write it down now. Change it from the Account tab
    after logging in, or reset it later via the Admin tab if you lose it.
```

**3. Managing it**

```bash
sudo systemctl status backup-armchair-quarterback   # is it running?
sudo systemctl restart backup-armchair-quarterback  # after editing backend/.env
journalctl -u backup-armchair-quarterback -f        # live logs
```

**To deploy an update**, either:

- Click **Update App** in the Admin tab (needs `ENABLE_SELF_UPDATE=true` in
  `backend/.env` — on by default for a fresh install via this script). It
  pulls, reinstalls, rebuilds, and restarts itself; see "Self-updating from
  the Admin tab" below for what that actually does and its limits.
- Or manually: `sudo git -C /opt/backup-armchair-quarterback pull --ff-only`,
  then re-run `sudo bash deploy/install.sh` to pick up any new dependencies
  and rebuild — safe to re-run any time, it won't touch your existing
  `backend/.env` or the SQLite database.

**Notes:**

- The script installs Python 3.12 (falling back to 3.11) via apt for the
  backend's virtualenv specifically, rather than trusting the OS
  default — a very new default Python (3.14+ on a sufficiently recent
  distro) can predate prebuilt wheels for some pinned dependency, and
  `pydantic-core`'s build tooling refuses outright to compile against
  anything past 3.13, even with a working Rust/C toolchain. If the OS's
  own apt repos don't carry python3.12 or python3.11 at all (seen on a
  very recent/unusual release), it fetches a portable Python 3.12 via
  [uv](https://docs.astral.sh/uv/) instead, which doesn't depend on
  what the OS packages. If you hit a wheel-build error on an older
  checkout of this script, `git pull` and re-run
  `sudo bash deploy/install.sh`: it detects a venv built on the wrong
  Python version and rebuilds it automatically.
- If your existing install predates this script deploying via git clone
  (it used to `rsync` a copy from wherever you'd cloned it, excluding
  `.git`), re-running install.sh migrates it automatically: `backend/.env`
  and `backend/data` are kept, everything else is replaced by a fresh
  clone. This is also what makes the Admin tab's Update button possible —
  it needs `/opt/backup-armchair-quarterback` to actually be a git checkout.
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

If you deployed via `install.sh`, log in with the admin account it printed
at the end instead of registering (see above) — it's already set up as an
admin, so you can skip straight to step 2.

1. Register an account on the login screen (just an email + password —
   this is a local account, unrelated to your ESPN login).
2. Find your league ID in the ESPN URL:
   `fantasy.espn.com/football/league?leagueId=123456` → `123456`.
3. On the **Setup** tab, enter the league ID and season, click **Sync
   League**.
4. Pick your team from the dropdown.
   - Private league, or want your real pending ESPN claims? Connect your
     ESPN account under **Settings → Account** first (see above), then sync.
5. Start on **Alerts** — it's what needs a decision right now — then use
   the **Roster**, **Start / Sit**, **Waivers**, **Schedule**, **Trades**,
   and **Trade Grader** tabs. Re-sync any time (e.g. once a week, or after
   a waiver run) to refresh projections and pull in the new week's stats —
   each sync adds to a running per-week history rather than throwing away
   past weeks, which is what the Trade Grader's rest-of-season values and
   the floor/ceiling labels are built from. Syncing regularly also makes
   the "what changed since your last sync" digest more useful, since it
   only ever compares the two most recent syncs.

Each teammate in your league can register their own account on the same
running instance and pick their own team — nobody sees anyone else's
selections or synced data. Anyone can change their own password from the
**Account** tab at any time (you'll need your current one). Forgot it
instead? There's no self-service email reset — the login page's "Forgot
password?" link just says to ask whoever manages your instance, which is
what the **Admin** tab's Reset Password action below is for.

## Admin: adding and removing accounts

Set `ADMIN_EMAILS` in `backend/.env` (comma-separated, case-insensitive) to
get an **Admin** tab, visible only to those accounts, for managing who else
can use this instance — an alternative to everyone self-registering.

- A fresh install via `install.sh` does this for you automatically: it
  creates an `admin@example.com` account with a random 10-character
  password (printed once at the end of the script — see above) and adds
  it to `ADMIN_EMAILS`, so there's someone who can log in and set everything
  else up without a chicken-and-egg problem. `admin` is the login's local
  part (`admin@...`) rather than a bare username, since the login form
  validates real email address syntax and rejects `admin@localhost`-style
  addresses. This only happens once, on a genuinely fresh install — an
  existing `backend/.env` is never touched, so re-running the script never
  creates a surprise second admin.
- **Add a person**: enter an email and a password (8+ characters) and share
  it with them directly — there's no invite email, so pick something you're
  comfortable telling them. They can change it themselves afterward from
  their own **Account** tab.
- **Reset someone's password**: for when they've forgotten it and can't use
  the Account tab themselves (no current password to enter there). Sets a
  new password directly, no email involved — share the new one with them
  the same way you'd share it when adding an account. This is the only
  "forgot password" flow this app has; there's no SMTP/email setup to
  configure, so keep this feature in mind before handing out accounts to
  people you won't be able to reach when they get locked out.
- **Remove a person**: deletes their account and everything scoped to it
  (synced leagues, team selection) — it doesn't touch anyone else's data.
  You can't remove your own account this way.
- Admin status isn't stored in the database — it's just whether your email
  is in `ADMIN_EMAILS`, the same way every other setting in `backend/.env`
  works. That sidesteps needing an existing admin to promote the first one.
  Like any `.env` change, restart the backend (`sudo systemctl restart
  backup-armchair-quarterback` on the standard deployment) for a change to
  `ADMIN_EMAILS` to take effect. Public self-registration
  (`/api/auth/register`) still works alongside this unless you also take it
  out of the login page yourself.

## Self-updating from the Admin tab

The **Update App** button (Admin tab, needs `ADMIN_EMAILS` set) is the
in-app equivalent of SSHing in and running `git pull && sudo bash
deploy/install.sh` by hand: it pulls the latest commit, reinstalls any
changed dependencies, rebuilds the frontend, then restarts the backend to
actually run the new code — all from one click, all in one request (which
can take a couple of minutes on a cold `npm install`; the button shows a
spinner and then polls until the backend comes back).

- **Off by default.** Set `ENABLE_SELF_UPDATE=true` in `backend/.env` to
  turn it on — a fresh install via `install.sh` does this automatically,
  since it's exactly the environment this needs (see below); anyone who
  set up `.env` by hand needs to opt in deliberately. It's meaningfully
  more powerful than anything else behind the admin gate, since it runs
  whatever code the next commit happens to contain.
- **Only works on the standard deployment.** It needs
  `/opt/backup-armchair-quarterback` to be its own git checkout that the
  `baq` service user fully owns — exactly what `install.sh` sets up (see
  "Deploying to a Proxmox Ubuntu container" above) — so it can update
  in place with no new permissions (no sudo, no root) beyond what the
  service already has. Nothing to do with local dev or a hand-rolled setup;
  there it just reports "not a git checkout" and does nothing.
- **Refuses to clobber anything.** It pulls with `--ff-only`, so a
  diverged or manually-modified checkout fails cleanly with the git error
  shown in the button's output rather than force-overwriting your history.
  If nothing's changed upstream, it says so and stops there — no rebuild,
  no restart.
- **No database migrations.** If a pulled change adds a new column (as
  several already have — see "Notes and limitations" below), the restarted
  backend will hit the same `no such column` error a manual update would;
  the fix is the same one documented there (delete `backend/data/fantasy.db`
  and re-sync). This button doesn't change that story, just automates
  everything before it.
- **A failure at any step is reported, not hidden** — the button's output
  shows each step (git pull, pip install, npm install, npm run build) and
  the tail of its output, so a broken pull is diagnosable from the browser
  instead of requiring a trip to `journalctl`.

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
  If it's unset or still the placeholder, the app generates a random key on
  first start and stores it at `backend/data/jwt_secret` (mode 0600) rather
  than signing with a value published in this repo — so sessions are never
  protected by a guessable secret, but set `JWT_SECRET` yourself if you want
  to control it (e.g. to share one key across machines). Sessions last 2
  weeks by default (`JWT_EXPIRE_MINUTES`) and can't be revoked early: logging
  out just discards the browser's copy, so a leaked token stays valid until
  it expires or you change the signing key.
- Repeated failed logins for the same email from the same address are
  throttled — 8 failures in 15 minutes returns `429` with a `Retry-After`
  until the window passes, which is enough to make online password guessing
  impractical. It's tracked in memory per worker (the deployed service runs
  two), so the real ceiling is roughly double, and it resets on restart.
- FastAPI's interactive docs (`/docs`, `/redoc`, `/openapi.json`) are off
  unless you set `ENABLE_API_DOCS=true`. Every endpoint requires auth either
  way; this just avoids publishing the API surface to everyone on your
  network.
- SQLite runs in WAL mode with a 30s busy timeout. A league sync is one long
  write transaction, and the deployed service runs two uvicorn workers — on
  the default rollback journal, a request landing mid-sync would fail with
  `database is locked`. WAL lets those reads proceed instead.
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
- Schema changes to `PlayerWeekStat`/`League` (the usage/advanced-stats,
  points-allowed, season-schedule, sync-digest and bench-points columns)
  only apply to a freshly created database — if you're upgrading an
  existing `backend/data/fantasy.db` from before these features, delete it
  and re-sync your league(s) rather than expecting new columns to appear on
  their own (there's no migration framework in this app). The symptom is a
  `no such column` error on sync.
- The **what changed** digest compares only the two most recent syncs, so
  it's empty until you've synced twice and it won't show anything that
  happened between syncs you skipped. Thresholds are deliberately coarse
  (5-point ownership moves, 3-point projection swings) to keep weekly noise
  out; every injury-status flip and roster move is reported regardless.
- Bye weeks and the multi-week outlook come from ESPN's public scoreboard
  API, one request per week of the season, cached on disk for a day
  (`backend/data/schedule_cache/`). The fantasy playoff weeks are assumed
  to be 15-17 (ESPN's standard default) rather than read from your league's
  actual playoff settings, so adjust mentally if your league differs. The
  bye-week collision warnings only cover single-position starting slots —
  FLEX-type slots draw from several positions, so they aren't checked.
- Floor/ceiling labels use thresholds relative to each player's own
  average (a "boom" is 1.5x their normal game), not position-wide cutoffs,
  and need at least 3 played weeks. Bye and inactive weeks are excluded
  rather than counted as zeros, which would otherwise drag every floor to 0.
- **Bench Points** reads each past week's lineup from ESPN's boxscore
  endpoint, since synced rosters only ever reflect right now. Weeks already
  computed are cached on the league, so only genuinely new weeks cost a
  request — except the current week, which is re-read every time since it's
  still accruing points. The "best possible lineup" is an exact
  maximum-value slot assignment (`backend/app/lineup.py`), not a greedy
  fill, and players who were on IR that week are correctly excluded from it
  since you couldn't have started them.
- Depth charts are **inferred, not ESPN's official depth chart** — ESPN
  doesn't expose one as data (only an HTML page), so players within each
  NFL team/position are ranked by nflverse's real snap % where a crosswalk
  match exists, falling back to ESPN's percent-started and then projected
  points otherwise. The player pool is whatever's synced into this league
  (rosters + free agents, currently top-200 by ownership — see
  `sync_service.py`), so very deep, widely-unowned bench players may not
  appear; that's fine since they wouldn't be meaningful handcuffs anyway.
  A handcuff is simply the next-ranked player at the same position on the
  same NFL team as one of your rostered RBs.

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
