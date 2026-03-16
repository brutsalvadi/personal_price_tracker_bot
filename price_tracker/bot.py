from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from price_tracker.charts import build_item_graph, build_all_graph, build_group_graph
from price_tracker.config import (
    Settings, _item_id,
    add_target_to_yaml, remove_target_from_yaml, update_threshold_in_yaml,
    add_to_group, remove_from_group, delete_group,
)
from price_tracker.db.database import get_latest_price, get_price_history, get_purchases, insert_purchase
from price_tracker.models import PurchaseRecord, TargetItem

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_S = 30
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class BotHandler:
    def __init__(self, settings: Settings, scheduler) -> None:
        self.settings = settings
        self.scheduler = scheduler
        self._offset: int = 0
        # Conversational state for /add: {chat_id: {"step": str, "data": dict}}
        self._pending: dict[int, dict] = {}

    # ── Polling ──────────────────────────────────────────────────────────────

    async def start_polling(self) -> None:
        logger.info("Bot command polling started")
        async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S + 5) as client:
            while True:
                try:
                    resp = await client.get(
                        self._url("getUpdates"),
                        params={
                            "offset": self._offset,
                            "timeout": _POLL_TIMEOUT_S,
                            "allowed_updates": ["message"],
                        },
                    )
                    resp.raise_for_status()
                    for update in resp.json().get("result", []):
                        self._offset = update["update_id"] + 1
                        await self._handle_update(update)
                except asyncio.CancelledError:
                    logger.info("Bot polling stopped")
                    return
                except Exception as exc:
                    logger.error("Polling error: %s", exc)
                    await asyncio.sleep(5)

    # ── Routing ──────────────────────────────────────────────────────────────

    async def _handle_update(self, update: dict) -> None:
        msg = update.get("message", {})
        chat_id: int | None = msg.get("chat", {}).get("id")
        text: str = (msg.get("text") or "").strip()

        if not chat_id or not text:
            return

        # Security: only the configured chat may control the bot
        if str(chat_id) != str(self.settings.telegram_chat_id):
            logger.warning("Ignored message from unauthorized chat_id %s", chat_id)
            return

        # Continue an in-progress /add conversation
        if chat_id in self._pending:
            await self._conversation_step(chat_id, text)
            return

        # Dispatch commands (strip optional @botname suffix)
        cmd = text.split()[0].lower().split("@")[0]
        if cmd in ("/help", "/start"):
            await self._cmd_help(chat_id)
        elif cmd == "/list":
            await self._cmd_list(chat_id)
        elif cmd == "/check":
            await self._cmd_check(chat_id, text)
        elif cmd == "/graph":
            await self._cmd_graph(chat_id, text)
        elif cmd == "/add":
            await self._cmd_add_start(chat_id)
        elif cmd == "/remove":
            await self._cmd_remove(chat_id, text)
        elif cmd == "/bought":
            await self._cmd_bought(chat_id, text)
        elif cmd == "/price":
            await self._cmd_price(chat_id, text)
        elif cmd == "/threshold":
            await self._cmd_threshold(chat_id, text)
        elif cmd == "/gadd":
            await self._cmd_gadd(chat_id, text)
        elif cmd == "/grem":
            await self._cmd_grem(chat_id, text)
        elif cmd == "/gdel":
            await self._cmd_gdel(chat_id, text)
        elif cmd == "/glist":
            await self._cmd_glist(chat_id)
        elif cmd == "/cancel":
            await self._send(chat_id, "Nothing to cancel.")

    # ── /help ────────────────────────────────────────────────────────────────

    async def _cmd_help(self, chat_id: int) -> None:
        await self._send(
            chat_id,
            "*Price Tracker*\n\n"
            "/list — show tracked items with latest prices\n"
            "/price _N_ — show latest stored price for one item\n"
            "/check — trigger an immediate scrape for all items\n"
            "/check _N_ — scrape one item\n"
            "/threshold _N_ _value_ — set alert threshold (use `off` to remove)\n"
            "/graph _N_ — price history chart for one item\n"
            "/graph all — % variation chart for all items\n"
            "/graph _G_ — % variation chart for a group\n"
            "/add — add a new product to track\n"
            "/bought _N_ — mark today's price as a purchase (★ on charts)\n"
            "/remove _N_ — stop tracking a product\n"
            "/gadd _N_ _G_ — add item N to group G\n"
            "/grem _N_ _G_ — remove item N from group G\n"
            "/gdel _G_ — delete a group entirely\n"
            "/glist — show all groups\n"
            "/cancel — abort an in-progress /add\n"
            "/help — show this message\n\n"
            "_N = number or name fragment, G = group letter_",
        )

    # ── /list ────────────────────────────────────────────────────────────────

    async def _cmd_list(self, chat_id: int) -> None:
        all_items = self.settings.targets

        if not all_items:
            await self._send(chat_id, "No items tracked yet. Use /add to add one.")
            return

        lines = ["*Tracked items:*\n"]
        for n, item in enumerate(all_items, start=1):
            latest = get_latest_price(item.item_id, self.settings.db_path)
            if latest:
                age = _relative_time(latest.scraped_at)
                lines.append(
                    f"{n}. [{item.name}]({item.url}): {latest.price:.2f} {item.currency} _({age})_"
                )
            else:
                lines.append(f"{n}. [{item.name}]({item.url}): not yet checked")
            if item.threshold is not None:
                lines.append(f"   Alert below: {item.threshold:.2f} {item.currency}")

        await self._send(chat_id, "\n".join(lines))

    # ── /check ───────────────────────────────────────────────────────────────

    async def _cmd_check(self, chat_id: int, text: str) -> None:
        from price_tracker.scheduler import _check_item  # avoid module-level circular

        parts = text.split(maxsplit=1)
        query = parts[1].strip() if len(parts) > 1 else None

        if query:
            item = self._resolve_item(query)
            if item is None:
                await self._send(chat_id, f"No item matching _{query}_. Use /list to see numbers.")
                return
            items = [item]
        else:
            items = self.settings.targets

        await self._send(chat_id, f"Checking {len(items)} item(s)…")
        lines = []
        for item in items:
            price = await _check_item(item, self.settings)
            if price is not None:
                lines.append(f"✅ *{item.name}*: {price:.2f} {item.currency}")
            else:
                lines.append(f"❌ *{item.name}*: scrape failed — check logs")
        await self._send(chat_id, "\n".join(lines))

    # ── Item resolver ─────────────────────────────────────────────────────────

    def _resolve_item(self, query: str) -> TargetItem | None:
        """Resolve a user query to a TargetItem.

        Accepts a 1-based index (e.g. "2") or a case-insensitive name fragment.
        """
        targets = self.settings.targets
        if query.isdigit():
            idx = int(query) - 1
            return targets[idx] if 0 <= idx < len(targets) else None
        q = query.lower()
        return next((i for i in targets if q in i.name.lower()), None)

    # ── /add (multi-step conversation) ───────────────────────────────────────

    async def _cmd_add_start(self, chat_id: int) -> None:
        self._pending[chat_id] = {"step": "name", "data": {}}
        await self._send(chat_id, "What's the *product name*?\n\n/cancel to abort.")

    async def _conversation_step(self, chat_id: int, text: str) -> None:
        if text.lower() == "/cancel":
            del self._pending[chat_id]
            await self._send(chat_id, "Cancelled.")
            return

        state = self._pending[chat_id]
        step = state["step"]

        if step == "name":
            state["data"]["name"] = text
            state["step"] = "url"
            await self._send(chat_id, "Send me the *product URL*:")

        elif step == "url":
            if not text.startswith("http"):
                await self._send(
                    chat_id,
                    "That doesn't look like a URL. Please send the full URL (starting with https://):",
                )
                return
            state["data"]["url"] = text
            state["step"] = "selector"
            await self._send(
                chat_id,
                "*CSS selector* for the price element:\n\n"
                "Tip: right\\-click the price → Inspect → right\\-click the element → Copy → Copy selector\n\n"
                "Example: `.a-price .a-offscreen`",
                parse_mode="MarkdownV2",
            )

        elif step == "selector":
            state["data"]["selector"] = text
            state["step"] = "threshold"
            await self._send(
                chat_id,
                "Alert *threshold* — send a number \\(e\\.g\\. `149\\.99`\\) to alert when the price drops below it, "
                "or /skip to alert on *any change*\\.",
                parse_mode="MarkdownV2",
            )

        elif step == "threshold":
            if text.lower() == "/skip":
                state["data"]["threshold"] = None
            else:
                try:
                    state["data"]["threshold"] = float(text.replace(",", "."))
                except ValueError:
                    await self._send(
                        chat_id, "Please send a number (e.g. `149.99`) or /skip:"
                    )
                    return
            state["step"] = "js_rendered"
            await self._send(
                chat_id,
                "Is this a *JavaScript-rendered* page (e.g. Amazon)?\n\n"
                "Reply `yes` or `no`. When in doubt, say `yes` — "
                "it's slower but works on all sites.",
            )

        elif step == "js_rendered":
            if text.lower() not in ("yes", "no", "y", "n"):
                await self._send(chat_id, "Please reply `yes` or `no`:")
                return
            state["data"]["js_rendered"] = text.lower() in ("yes", "y")
            await self._finish_add(chat_id, state["data"])
            del self._pending[chat_id]

    async def _finish_add(self, chat_id: int, data: dict) -> None:
        from price_tracker.scheduler import add_item_job

        default_interval = (
            self.settings.targets[0].interval_minutes if self.settings.targets else 60
        )
        threshold = data.get("threshold")
        item = TargetItem(
            name=data["name"],
            url=data["url"],
            selector=[data["selector"]],
            item_id=_item_id(data["name"], data["url"]),
            selector_type="css",
            interval_minutes=default_interval,
            threshold=threshold,
            alert_on="price_drop" if threshold is not None else "any_change",
            js_rendered=data["js_rendered"],
            currency="EUR",
        )

        add_target_to_yaml(item, self.settings.config_path)
        self.settings.targets.append(item)
        add_item_job(self.scheduler, item, self.settings)

        threshold_str = (
            f"{item.threshold:.2f} {item.currency}" if item.threshold is not None else "any change"
        )
        await self._send(
            chat_id,
            f"✅ *Added:* {item.name}\n"
            f"Selector: `{item.selector[0]}`\n"
            f"Alert on: {threshold_str}\n"
            f"Scraper: {'Playwright \\(JS\\)' if item.js_rendered else 'static'}\n"
            f"Checks every {item.interval_minutes} min — first check starting now…",
        )

    # ── /graph ───────────────────────────────────────────────────────────────

    async def _cmd_graph(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: /graph _N_ or /graph all")
            return

        query = parts[1].strip()

        if query.lower() == "all":
            targets = self.settings.targets
            if not targets:
                await self._send(chat_id, "No items tracked yet.")
                return
            all_history = [
                (item, get_price_history(item.item_id, self.settings.db_path))
                for item in targets
            ]
            usable = [(item, h) for item, h in all_history if len(h) >= 1]
            if not usable:
                await self._send(chat_id, "No price data yet for any item.")
                return
            all_purchases = {
                item.item_id: get_purchases(item.item_id, self.settings.db_path)
                for item, _ in usable
            }
            buf = build_all_graph(usable, all_purchases)
            total = sum(len(h) for _, h in usable)
            caption = f"📊 *All products* — % change from first reading ({total} readings across {len(usable)} item(s))"
            await self._send_photo(chat_id, buf, caption)
            return

        # Check if query is a group id (before trying item resolver)
        if query.upper() in self.settings.groups:
            group_items = self._resolve_group_items(query)
            if not group_items:
                await self._send(chat_id, f"Group *{query.upper()}* exists but has no tracked items.")
                return
            all_history = [(item, get_price_history(item.item_id, self.settings.db_path)) for item in group_items]
            usable = [(item, h) for item, h in all_history if len(h) >= 1]
            if not usable:
                await self._send(chat_id, f"No price data yet for any item in group *{query.upper()}*.")
                return
            all_purchases = {item.item_id: get_purchases(item.item_id, self.settings.db_path) for item, _ in usable}
            buf = build_group_graph(query.upper(), usable, all_purchases)
            total = sum(len(h) for _, h in usable)
            caption = f"📊 *Group {query.upper()}* — price history ({total} readings, {len(usable)} items)"
            await self._send_photo(chat_id, buf, caption)
            return

        item = self._resolve_item(query)
        if item is None:
            await self._send(chat_id, f"No item matching _{query}_. Use /list to see numbers.")
            return

        history = get_price_history(item.item_id, self.settings.db_path)
        if len(history) < 2:
            await self._send(chat_id, f"Not enough data yet for *{item.name}* — only {len(history)} reading(s) recorded.")
            return

        purchases = get_purchases(item.item_id, self.settings.db_path)
        buf = build_item_graph(item, history, purchases)
        caption = f"📈 *{item.name}* — {len(history)} readings"
        await self._send_photo(chat_id, buf, caption)

    # ── /price ───────────────────────────────────────────────────────────────

    async def _cmd_price(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: /price _N_")
            return
        item = self._resolve_item(parts[1].strip())
        if item is None:
            await self._send(chat_id, f"No item matching _{parts[1].strip()}_.")
            return
        latest = get_latest_price(item.item_id, self.settings.db_path)
        if latest is None:
            await self._send(chat_id, f"No price recorded yet for *{item.name}*.")
            return
        age = _relative_time(latest.scraped_at)
        threshold_str = f"\nAlert below: {item.threshold:.2f} {item.currency}" if item.threshold is not None else ""
        await self._send(chat_id, f"*{item.name}*\n{latest.price:.2f} {item.currency} _({age})_{threshold_str}")

    # ── /threshold ───────────────────────────────────────────────────────────

    async def _cmd_threshold(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await self._send(chat_id, "Usage: /threshold _N_ _value_ or /threshold _N_ off")
            return
        item = self._resolve_item(parts[1].strip())
        if item is None:
            await self._send(chat_id, f"No item matching _{parts[1].strip()}_.")
            return
        raw_value = parts[2].strip().lower()
        if raw_value == "off":
            new_threshold = None
        else:
            try:
                new_threshold = float(raw_value.replace(",", "."))
            except ValueError:
                await self._send(chat_id, "Value must be a number or `off`.")
                return

        item.threshold = new_threshold
        item.alert_on = "price_drop" if new_threshold is not None else "any_change"
        update_threshold_in_yaml(item.item_id, new_threshold, self.settings.config_path)

        if new_threshold is not None:
            await self._send(chat_id, f"✅ *{item.name}*: threshold set to {new_threshold:.2f} {item.currency}")
        else:
            await self._send(chat_id, f"✅ *{item.name}*: threshold removed (alerting on any change)")

    # ── /bought ──────────────────────────────────────────────────────────────

    async def _cmd_bought(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: /bought _N_ — use the number from /list")
            return

        item = self._resolve_item(parts[1].strip())
        if item is None:
            await self._send(chat_id, f"No item matching _{parts[1].strip()}_. Use /list to see numbers.")
            return

        latest = get_latest_price(item.item_id, self.settings.db_path)
        price = latest.price if latest else 0.0
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        insert_purchase(
            PurchaseRecord(
                item_id=item.item_id,
                item_name=item.name,
                price=price,
                currency=item.currency,
                bought_at=now,
            ),
            self.settings.db_path,
        )
        price_str = f"{price:.2f} {item.currency}" if latest else "unknown price"
        await self._send(chat_id, f"★ Marked *{item.name}* as purchased at {price_str}")

    # ── Groups ───────────────────────────────────────────────────────────────

    def _resolve_group_items(self, group_id: str) -> list[TargetItem] | None:
        """Return the TargetItems in a group, or None if the group doesn't exist."""
        gid = group_id.upper()
        item_ids = self.settings.groups.get(gid)
        if item_ids is None:
            return None
        by_id = {t.item_id: t for t in self.settings.targets}
        return [by_id[iid] for iid in item_ids if iid in by_id]

    async def _cmd_gadd(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await self._send(chat_id, "Usage: /gadd _N_ _G_  (e.g. /gadd 2 A)")
            return
        item = self._resolve_item(parts[1].strip())
        if item is None:
            await self._send(chat_id, f"No item matching _{parts[1].strip()}_.")
            return
        gid = parts[2].strip().upper()
        add_to_group(gid, item.item_id, self.settings.groups, self.settings.config_path)
        await self._send(chat_id, f"✅ Added *{item.name}* to group *{gid}*")

    async def _cmd_grem(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            await self._send(chat_id, "Usage: /grem _N_ _G_")
            return
        item = self._resolve_item(parts[1].strip())
        if item is None:
            await self._send(chat_id, f"No item matching _{parts[1].strip()}_.")
            return
        gid = parts[2].strip().upper()
        if gid not in self.settings.groups or item.item_id not in self.settings.groups[gid]:
            await self._send(chat_id, f"*{item.name}* is not in group *{gid}*.")
            return
        remove_from_group(gid, item.item_id, self.settings.groups, self.settings.config_path)
        if gid in self.settings.groups:
            await self._send(chat_id, f"✅ Removed *{item.name}* from group *{gid}*")
        else:
            await self._send(chat_id, f"✅ Removed *{item.name}* from group *{gid}* (group is now empty and was deleted)")

    async def _cmd_gdel(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: /gdel _G_")
            return
        gid = parts[1].strip().upper()
        if gid not in self.settings.groups:
            await self._send(chat_id, f"Group *{gid}* does not exist.")
            return
        delete_group(gid, self.settings.groups, self.settings.config_path)
        await self._send(chat_id, f"🗑 Deleted group *{gid}* (items are still tracked)")

    async def _cmd_glist(self, chat_id: int) -> None:
        if not self.settings.groups:
            await self._send(chat_id, "No groups defined yet. Use /gadd _N_ _G_ to create one.")
            return
        by_id = {t.item_id: t for t in self.settings.targets}
        lines = ["*Groups:*\n"]
        for gid, item_ids in sorted(self.settings.groups.items()):
            names = [by_id[iid].name for iid in item_ids if iid in by_id]
            lines.append(f"*{gid}*: {', '.join(names) if names else '(empty)'}")
        await self._send(chat_id, "\n".join(lines))

    # ── /remove ──────────────────────────────────────────────────────────────

    async def _cmd_remove(self, chat_id: int, text: str) -> None:
        from price_tracker.scheduler import remove_item_job

        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await self._send(chat_id, "Usage: /remove _N_ — use the number from /list")
            return

        query = parts[1].strip()
        match = self._resolve_item(query)

        if match is None:
            await self._send(
                chat_id,
                f"No item matching _{query}_. Use /list to see numbers.",
            )
            return

        remove_target_from_yaml(match.item_id, self.settings.config_path)
        self.settings.targets = [t for t in self.settings.targets if t.item_id != match.item_id]
        remove_item_job(self.scheduler, match.item_id)
        await self._send(chat_id, f"🗑 Removed: *{match.name}*")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _url(self, method: str) -> str:
        return _TELEGRAM_API.format(token=self.settings.telegram_bot_token, method=method)

    async def _send(
        self, chat_id: int, text: str, parse_mode: str = "Markdown"
    ) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                await client.post(
                    self._url("sendMessage"),
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
            except httpx.HTTPError as exc:
                logger.error("Failed to send message to %s: %s", chat_id, exc)

    async def _send_photo(self, chat_id: int, buf: bytes, caption: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                await client.post(
                    self._url("sendPhoto"),
                    data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                    files={"photo": ("graph.png", buf, "image/png")},
                )
            except httpx.HTTPError as exc:
                logger.error("Failed to send photo to %s: %s", chat_id, exc)


def _relative_time(iso: str) -> str:
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        minutes = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
        if minutes < 2:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except ValueError:
        return iso


