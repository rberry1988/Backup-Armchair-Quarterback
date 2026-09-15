"""Background auto-sync: re-runs a league's ESPN sync on a schedule so the
data stays fresh without anyone clicking Sync League.

Runs as an asyncio task inside the API process rather than a separate
service, a cron entry, or a new scheduling dependency — one moving part
instead of two on a single-box deployment. The systemd unit runs uvicorn
with --workers 2, though, so this loop exists in *both* processes: every
due league is therefore claimed with a compare-and-swap on auto_synced_at
before any work starts, and only the worker that wins the swap syncs it.

A sync is a long blocking call (four external APIs plus a few thousand
SQLite writes), so it's handed to a worker thread rather than run on the
event loop that's also serving requests.
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from sqlalchemy import update

from app.db import SessionLocal
from app.models import League
from app.sync_service import sync_league

logger = logging.getLogger(__name__)

# How often to look for due leagues — comfortably below the shortest
# interval anyone can pick, so a league never drifts far past its due time.
CHECK_INTERVAL_SECONDS = 5 * 60

MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 168  # a week
DEFAULT_INTERVAL_HOURS = 12
# Trimmed before storing: this is surfaced in the UI, and an upstream error
# can carry a whole response body.
MAX_ERROR_CHARS = 300


def clamp_interval_hours(hours: int | None) -> int:
    if not hours:
        return DEFAULT_INTERVAL_HOURS
    return max(MIN_INTERVAL_HOURS, min(hours, MAX_INTERVAL_HOURS))


def _due_leagues(db, now: datetime.datetime) -> list[tuple[int, datetime.datetime | None]]:
    """(league_id, auto_synced_at) for every league whose next sync is due.
    The second value is what the claim below compares against."""
    due = []
    for league in db.query(League).filter(League.auto_sync_enabled.is_(True)).all():
        interval = clamp_interval_hours(league.auto_sync_interval_hours)
        last_attempt = league.auto_synced_at
        if last_attempt is None or (now - last_attempt) >= datetime.timedelta(hours=interval):
            due.append((league.id, last_attempt))
    return due


def _claim(db, league_id: int, previous: datetime.datetime | None, now: datetime.datetime) -> bool:
    """Compare-and-swap auto_synced_at from the value we just read to now.
    Exactly one of the two uvicorn workers can win this, so a league is
    never synced twice concurrently. Stamping the attempt time (rather than
    only successes) is also what keeps a league that fails every time from
    being retried in a tight loop — it waits out the full interval."""
    guard = League.auto_synced_at.is_(None) if previous is None else League.auto_synced_at == previous
    result = db.execute(
        update(League).where(League.id == league_id, guard).values(auto_synced_at=now)
    )
    db.commit()
    return result.rowcount == 1


def _sync_one(league_id: int) -> None:
    """Sync one claimed league, recording the outcome. Deliberately catches
    everything: one league's bad ESPN response must not stop the loop or
    take down the worker it runs in."""
    db = SessionLocal()
    try:
        league = db.get(League, league_id)
        if league is None:
            return
        user_id, espn_league_id, season = league.user_id, league.espn_league_id, league.season
        try:
            sync_league(db, user_id=user_id, espn_league_id=espn_league_id, season=season)
            error = None
        except Exception as exc:  # noqa: BLE001 — see docstring
            db.rollback()
            error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
            logger.warning("Auto-sync failed for league %s: %s", league_id, error)

        league = db.get(League, league_id)
        if league is not None:
            league.auto_sync_error = error
            db.commit()
    finally:
        db.close()


async def run_due_syncs() -> None:
    now = datetime.datetime.utcnow()
    db = SessionLocal()
    try:
        claimed = [
            league_id for league_id, previous in _due_leagues(db, now) if _claim(db, league_id, previous, now)
        ]
    finally:
        db.close()

    for league_id in claimed:
        await asyncio.to_thread(_sync_one, league_id)


async def auto_sync_loop() -> None:
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            await run_due_syncs()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a scheduler that dies on one bad pass is useless
            logger.exception("Auto-sync pass failed")
