from __future__ import annotations

import json
import logging

import requests
from bs4 import BeautifulSoup

from price_tracker.models import TargetItem
from price_tracker.scrapers.base import BaseScraper, ScraperError, normalize_price

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class StaticScraper(BaseScraper):
    """Scraper for pages that don't require JavaScript rendering."""

    @property
    def scraper_name(self) -> str:
        return "static"

    async def scrape(self, item: TargetItem) -> float:
        logger.debug("Static scrape: %s  url=%s", item.name, item.url)
        try:
            resp = requests.get(item.url, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScraperError(f"HTTP error for {item.url}: {exc}") from exc

        soup = BeautifulSoup(resp.text, "lxml")

        if item.selector_type == "json_ld":
            raw_text = self._extract_json_ld(soup, item)
        else:
            raw_text = self._extract(soup, item)
        if raw_text is None:
            raise ScraperError(
                f"None of {len(item.selector)} selector(s) ({item.selector_type}) "
                f"matched on {item.url}: "
                + ", ".join(repr(s) for s in item.selector)
            )

        try:
            price = normalize_price(raw_text)
        except ValueError as exc:
            raise ScraperError(str(exc)) from exc

        logger.info("Static scrape OK: %s  price=%.2f %s", item.name, price, item.currency)
        return price

    def _extract_json_ld(self, soup: BeautifulSoup, item: TargetItem) -> str | None:
        """Walk a dot-notation path (e.g. 'offers.price') into JSON-LD Product data."""
        path = item.selector[0]
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for obj in (data if isinstance(data, list) else [data]):
                if not isinstance(obj, dict) or obj.get("@type") != "Product":
                    continue
                value: object = obj
                for key in path.split("."):
                    value = value.get(key) if isinstance(value, dict) else None
                if value is not None:
                    return str(value)
        return None

    def _extract(self, soup: BeautifulSoup, item: TargetItem) -> str | None:
        if item.selector_type == "css":
            for sel in item.selector:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(strip=True)
            return None
        else:
            # xpath via lxml etree
            from lxml import etree  # noqa: PLC0415

            tree = etree.fromstring(soup.encode(), etree.HTMLParser())
            for sel in item.selector:
                results = tree.xpath(sel)
                if results:
                    node = results[0]
                    text = node.strip() if isinstance(node, str) else (node.text or "").strip()
                    if text:
                        return text
            return None
