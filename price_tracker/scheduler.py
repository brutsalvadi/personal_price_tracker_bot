from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from apscheduler.jobstores.base import JobLookupError

from price_tracker.config import Settings
from price_tracker.db.database import get_latest_price, get_price_history, insert_alert, insert_price
from price_tracker.models import AlertRecord, PriceRecord, TargetItem
from price_tracker.notifier import send_alert
from price_tracker.scrapers.base import ScraperError
from price_tracker.scrapers.playwright_scraper import PlaywrightScraper
from price_tracker.scrapers.static import StaticScraper

logger = logging.getLogger(__name__)

_static_scraper = StaticScraper()
_playwright_scraper: PlaywrightScraper | None = None


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _should_alert(
    item: TargetItem,
    new_price: float,
    previous: PriceRecord | None,
) -> bool:
    """
    Decide whether to fire an alert.

    Rules:
    - Never alert on the first reading (no previous record).
    - price_drop mode: alert only when new_price < threshold AND new_price < previous price.
    - any_change mode: alert whenever price differs from previous.
    """
    if previous is None:
        return False

    if item.alert_on == "any_change":
        return new_price != previous.price

    # price_drop mode
    if item.threshold is None:
        # No threshold set — alert on any price decrease
        return new_price < previous.price

    return new_price < item.threshold and new_price < previous.price


async def _check_item(item: TargetItem, settings: Settings) -> float | None:
    """Scrape *item*, persist the result, and fire an alert if warranted.

    Returns the scraped price on success, or None if the scrape failed.
    """
    global _playwright_scraper

    logger.debug("Checking item: %s", item.name)

    if item.js_rendered:
        if _playwright_scraper is None:
            _playwright_scraper = PlaywrightScraper()
        scraper = _playwright_scraper
    else:
        scraper = _static_scraper

    try:
        price = await scraper.scrape(item)
    except ScraperError as exc:
        logger.error("Scrape failed for %s: %s", item.name, exc)
        return None

    previous = get_latest_price(item.item_id, settings.db_path)

    record = PriceRecord(
        item_id=item.item_id,
        item_name=item.name,
        price=price,
        currency=item.currency,
        url=item.url,
        scraped_at=_now_utc(),
        scraper=scraper.scraper_name,
    )
    insert_price(record, settings.db_path)

    if _should_alert(item, price, previous):
        alert = AlertRecord(
            item_id=item.item_id,
            item_name=item.name,
            triggered_price=price,
            previous_price=previous.price if previous else None,
            threshold=item.threshold,
            alert_type=item.alert_on,
            sent_at=_now_utc(),
            telegram_ok=False,  # will be updated
        )
        history = get_price_history(item.item_id, settings.db_path)
        ok = await send_alert(
            item, alert, settings.telegram_bot_token, settings.telegram_chat_id,
            history=history,
        )
        alert.telegram_ok = ok
        insert_alert(alert, settings.db_path)

    return price


def add_item_job(
    scheduler: AsyncIOScheduler, item: TargetItem, settings: Settings
) -> None:
    """Add (or replace) a scheduler job for *item*."""
    scheduler.add_job(
        _check_item,
        trigger=IntervalTrigger(minutes=item.interval_minutes),
        args=[item, settings],
        id=f"check_{item.item_id}",
        name=item.name,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,  # allow up to 5 min late — jobs share the same tick
        next_run_time=datetime.now(timezone.utc),
        replace_existing=True,
    )
    logger.info(
        "Scheduled '%s' every %d min (id=%s)",
        item.name,
        item.interval_minutes,
        item.item_id,
    )


def remove_item_job(scheduler: AsyncIOScheduler, item_id: str) -> None:
    """Remove the scheduler job for *item_id*, ignoring missing jobs."""
    try:
        scheduler.remove_job(f"check_{item_id}")
        logger.info("Removed job for item_id=%s", item_id)
    except JobLookupError:
        logger.warning("Job check_%s not found in scheduler", item_id)


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Create and configure an AsyncIOScheduler with one job per target item."""
    scheduler = AsyncIOScheduler()

    for item in settings.targets:
        add_item_job(scheduler, item, settings)

    return scheduler
