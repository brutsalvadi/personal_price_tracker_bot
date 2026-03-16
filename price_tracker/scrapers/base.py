from __future__ import annotations

import re
from abc import ABC, abstractmethod

from price_tracker.models import TargetItem


def normalize_price(raw: str) -> float:
    """
    Convert a raw price string scraped from a web page into a float.

    Handles common formats:
    - "1.299,99 €"  → 1299.99   (European: dot=thousands, comma=decimal)
    - "1,299.99"    → 1299.99   (US/UK: comma=thousands, dot=decimal)
    - "$1,299"      → 1299.0
    - "249"         → 249.0
    - "249,99"      → 249.99    (European decimal, no thousands sep)
    - "1.299"       → 1299.0    (European thousands, no decimal)

    Raises ValueError if no numeric content is found.
    """
    # Strip currency symbols, whitespace, and non-numeric punctuation at edges
    cleaned = raw.strip()
    cleaned = re.sub(r"[^\d.,]", "", cleaned)

    if not cleaned:
        raise ValueError(f"No numeric content in price string: {raw!r}")

    dot_count = cleaned.count(".")
    comma_count = cleaned.count(",")

    if dot_count == 0 and comma_count == 0:
        # Plain integer e.g. "249"
        return float(cleaned)

    if dot_count == 1 and comma_count == 0:
        # Could be decimal ("249.99") or thousands ("1.299")
        parts = cleaned.split(".")
        if len(parts[1]) == 3:
            # Likely European thousands separator: "1.299"
            return float(cleaned.replace(".", ""))
        return float(cleaned)

    if comma_count == 1 and dot_count == 0:
        # Could be decimal ("249,99") or thousands ("1,299")
        parts = cleaned.split(",")
        if len(parts[1]) == 3:
            # Likely thousands separator: "1,299"
            return float(cleaned.replace(",", ""))
        # Decimal comma: "249,99"
        return float(cleaned.replace(",", "."))

    # Both separators present — determine which is thousands and which is decimal
    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")

    if last_dot > last_comma:
        # Dot is decimal separator: "1,299.99" (US format)
        return float(cleaned.replace(",", ""))
    else:
        # Comma is decimal separator: "1.299,99" (EU format)
        return float(cleaned.replace(".", "").replace(",", "."))


class BaseScraper(ABC):
    """Abstract base for all price scrapers."""

    @abstractmethod
    async def scrape(self, item: TargetItem) -> float:
        """
        Fetch the page for *item* and return the normalised price as a float.
        Raises ScraperError on failure.
        """

    @property
    @abstractmethod
    def scraper_name(self) -> str:
        """Short identifier stored in PriceRecord.scraper."""


class ScraperError(Exception):
    """Raised when a scraper cannot obtain a price."""
