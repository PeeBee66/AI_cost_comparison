"""Tiny asyncio-based nightly scheduler. No external deps."""
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

from app.config import ENABLE_NIGHTLY, NIGHTLY_HOUR_UTC, NIGHTLY_MINUTE_UTC

log = logging.getLogger(__name__)


def _seconds_until_next(hour: int, minute: int) -> float:
    now = datetime.now(timezone.utc)
    target = datetime.combine(now.date(), time(hour, minute, tzinfo=timezone.utc))
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def nightly_loop(refresh_callable, lock: asyncio.Lock) -> None:
    """Sleep until NIGHTLY_HOUR_UTC:NIGHTLY_MINUTE_UTC then run a refresh. Repeat forever."""
    if not ENABLE_NIGHTLY:
        log.info("Nightly refresh disabled via ENABLE_NIGHTLY=0")
        return

    while True:
        wait = _seconds_until_next(NIGHTLY_HOUR_UTC, NIGHTLY_MINUTE_UTC)
        log.info(
            "Next nightly refresh in %.0f min (at %02d:%02d UTC)",
            wait / 60,
            NIGHTLY_HOUR_UTC,
            NIGHTLY_MINUTE_UTC,
        )
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            log.info("Nightly scheduler cancelled")
            raise

        if lock.locked():
            log.info("Manual refresh in progress; skipping nightly tick")
            # avoid a tight loop if we wake up exactly on the boundary
            await asyncio.sleep(60)
            continue

        log.info("Nightly refresh starting")
        async with lock:
            try:
                await refresh_callable(do_scrape=True, do_discovery=True)
                log.info("Nightly refresh complete")
            except Exception:
                log.exception("Nightly refresh failed")
