from __future__ import annotations

import logging
from pathlib import Path

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage

from price_tracker.models import AlertRecord, PriceRecord, PurchaseRecord

logger = logging.getLogger(__name__)

_db: TinyDB | None = None


def get_db(db_path: str | Path = "data/db.json") -> TinyDB:
    """Return the singleton TinyDB instance, creating it if necessary."""
    global _db
    if _db is None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _db = TinyDB(path, storage=JSONStorage, indent=2)
        logger.debug("Opened TinyDB at %s", path)
    return _db


def close_db() -> None:
    global _db
    if _db is not None:
        _db.close()
        _db = None


def insert_price(record: PriceRecord, db_path: str | Path = "data/db.json") -> None:
    db = get_db(db_path)
    db.table("prices").insert(record.to_dict())
    logger.debug(
        "Inserted price record: item_id=%s price=%.2f", record.item_id, record.price
    )


def get_latest_price(
    item_id: str, db_path: str | Path = "data/db.json"
) -> PriceRecord | None:
    """Return the most recent PriceRecord for *item_id*, or None if none exists."""
    db = get_db(db_path)
    Item = Query()
    rows = db.table("prices").search(Item.item_id == item_id)
    if not rows:
        return None
    # Records are ISO-8601 strings — lexicographic sort is correct for UTC timestamps
    latest = max(rows, key=lambda r: r["scraped_at"])
    return PriceRecord(
        item_id=latest["item_id"],
        item_name=latest["item_name"],
        price=latest["price"],
        currency=latest["currency"],
        url=latest["url"],
        scraped_at=latest["scraped_at"],
        scraper=latest["scraper"],
    )


def get_price_history(
    item_id: str, db_path: str | Path = "data/db.json"
) -> list[PriceRecord]:
    """Return all PriceRecords for *item_id* sorted oldest-first."""
    db = get_db(db_path)
    Item = Query()
    rows = db.table("prices").search(Item.item_id == item_id)
    rows.sort(key=lambda r: r["scraped_at"])
    return [
        PriceRecord(
            item_id=r["item_id"],
            item_name=r["item_name"],
            price=r["price"],
            currency=r["currency"],
            url=r["url"],
            scraped_at=r["scraped_at"],
            scraper=r["scraper"],
        )
        for r in rows
    ]


def insert_alert(record: AlertRecord, db_path: str | Path = "data/db.json") -> None:
    db = get_db(db_path)
    db.table("alerts").insert(record.to_dict())
    logger.debug(
        "Inserted alert record: item_id=%s type=%s", record.item_id, record.alert_type
    )


def insert_purchase(record: PurchaseRecord, db_path: str | Path = "data/db.json") -> None:
    db = get_db(db_path)
    db.table("purchases").insert(record.to_dict())
    logger.debug(
        "Inserted purchase record: item_id=%s price=%.2f", record.item_id, record.price
    )


def get_purchases(
    item_id: str, db_path: str | Path = "data/db.json"
) -> list[PurchaseRecord]:
    """Return all PurchaseRecords for *item_id* sorted oldest-first."""
    db = get_db(db_path)
    Item = Query()
    rows = db.table("purchases").search(Item.item_id == item_id)
    rows.sort(key=lambda r: r["bought_at"])
    return [
        PurchaseRecord(
            item_id=r["item_id"],
            item_name=r["item_name"],
            price=r["price"],
            currency=r["currency"],
            bought_at=r["bought_at"],
        )
        for r in rows
    ]

