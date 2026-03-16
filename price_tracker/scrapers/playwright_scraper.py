from __future__ import annotations

import asyncio
import logging

import os

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

from price_tracker.models import TargetItem
from price_tracker.scrapers.base import BaseScraper, ScraperError, normalize_price

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 60_000
_DEFAULT_WAIT_MS = 10_000

# Only one Chromium instance at a time — prevents OOM on resource-constrained hosts
# (e.g. Raspberry Pi) when multiple JS-rendered items are scheduled simultaneously.
_playwright_semaphore = asyncio.Semaphore(1)


class PlaywrightScraper(BaseScraper):
    """Scraper for JS-rendered pages using headless Chromium via Playwright."""

    @property
    def scraper_name(self) -> str:
        return "playwright"

    async def scrape(self, item: TargetItem) -> float:
        logger.debug("Playwright scrape: %s  url=%s", item.name, item.url)
        try:
            raw_text = await self._fetch(item)
        except PWTimeoutError as exc:
            raise ScraperError(f"Playwright timeout for {item.url}: {exc}") from exc
        except Exception as exc:
            raise ScraperError(f"Playwright error for {item.url}: {exc}") from exc

        if raw_text is None:
            raise ScraperError(
                f"None of {len(item.selector)} selector(s) matched on {item.url}: "
                + ", ".join(repr(s) for s in item.selector)
            )

        try:
            price = normalize_price(raw_text)
        except ValueError as exc:
            raise ScraperError(str(exc)) from exc

        logger.info(
            "Playwright scrape OK: %s  price=%.2f %s", item.name, price, item.currency
        )
        return price

    async def _fetch(self, item: TargetItem) -> str | None:
        async with _playwright_semaphore:
            async with async_playwright() as pw:
                launch_kwargs: dict = {
                    "headless": True,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                chromium_path = os.environ.get("CHROMIUM_PATH")
                if chromium_path:
                    launch_kwargs["executable_path"] = chromium_path
                browser = await pw.chromium.launch(**launch_kwargs)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    locale="es-ES",
                    viewport={"width": 1280, "height": 800},
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                    },
                )
                page = await context.new_page()
                # Hide the webdriver flag that bot-detection scripts look for
                await page.add_init_script(
                    "delete Object.getPrototypeOf(navigator).webdriver"
                )
                await page.goto(item.url, timeout=_DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
                await _accept_cookies(page)

                for i, sel in enumerate(item.selector):
                    selector_str = sel if item.selector_type == "css" else f"xpath={sel}"
                    # Give the first selector the full wait; subsequent ones a short
                    # timeout since the page is already loaded
                    wait_ms = _DEFAULT_WAIT_MS if i == 0 else 3_000
                    locator = page.locator(selector_str).first
                    try:
                        await locator.wait_for(timeout=wait_ms)
                        raw = await locator.inner_text()
                        if raw and raw.strip():
                            logger.debug("Selector %r matched on %s", sel, item.url)
                            return raw.strip()
                    except PWTimeoutError:
                        logger.debug("Selector %r timed out on %s", sel, item.url)

                title = await page.title()
                logger.warning(
                    "No selector matched on %s — page title: %r — tried: %s",
                    item.url, title, ", ".join(repr(s) for s in item.selector),
                )
                return None


# Cookie consent button selectors, tried in order (covers Amazon, common GDPR banners)
_COOKIE_SELECTORS = [
    "#sp-cc-accept",                          # Amazon
    "[data-testid='accept-all-button']",
    "#onetrust-accept-btn-handler",
    "button[id*='accept']",
    "button[class*='accept']",
]


async def _accept_cookies(page) -> None:
    """Click the cookies consent button if one is visible, then wait for it to dismiss."""
    for sel in _COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=5_000):
                await btn.click()
                logger.debug("Accepted cookies via %r", sel)
                # Give AJAX price widgets time to load after consent
                try:
                    await page.wait_for_load_state("networkidle", timeout=8_000)
                except PWTimeoutError:
                    pass  # Best-effort; continue with whatever rendered
                return
        except PWTimeoutError:
            continue
        except Exception:
            continue
