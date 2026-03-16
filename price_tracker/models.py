from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class TargetItem:
    name: str
    url: str
    selector: list[str]
    item_id: str                                    # deterministic hash of name+url
    selector_type: Literal["css", "xpath", "json_ld"] = "css"
    interval_minutes: int = 60
    threshold: float | None = None
    alert_on: Literal["price_drop", "any_change"] = "price_drop"
    js_rendered: bool = False
    currency: str = "EUR"


@dataclass
class PriceRecord:
    item_id: str
    item_name: str
    price: float
    currency: str
    url: str
    scraped_at: str                                 # ISO-8601 UTC string
    scraper: Literal["static", "playwright"]

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "price": self.price,
            "currency": self.currency,
            "url": self.url,
            "scraped_at": self.scraped_at,
            "scraper": self.scraper,
        }


@dataclass
class PurchaseRecord:
    item_id: str
    item_name: str
    price: float
    currency: str
    bought_at: str                                  # ISO-8601 UTC string

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "price": self.price,
            "currency": self.currency,
            "bought_at": self.bought_at,
        }


@dataclass
class AlertRecord:
    item_id: str
    item_name: str
    triggered_price: float
    previous_price: float | None
    threshold: float | None
    alert_type: Literal["price_drop", "any_change"]
    sent_at: str                                    # ISO-8601 UTC string
    telegram_ok: bool

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "triggered_price": self.triggered_price,
            "previous_price": self.previous_price,
            "threshold": self.threshold,
            "alert_type": self.alert_type,
            "sent_at": self.sent_at,
            "telegram_ok": self.telegram_ok,
        }
