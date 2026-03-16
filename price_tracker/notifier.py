from __future__ import annotations

import logging

import httpx

from price_tracker.models import AlertRecord, PriceRecord, TargetItem

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _format_message(item: TargetItem, record: AlertRecord) -> str:
    lines = [f"*Price alert: {item.name}*"]

    if record.alert_type == "price_drop":
        lines.append(
            f"Price dropped to *{record.triggered_price:.2f} {item.currency}*"
        )
        if record.threshold is not None:
            lines.append(f"Threshold: {record.threshold:.2f} {item.currency}")
    else:
        lines.append(f"New price: *{record.triggered_price:.2f} {item.currency}*")

    if record.previous_price is not None:
        lines.append(
            f"Previous: {record.previous_price:.2f} {item.currency}"
        )

    lines.append(f"[View product]({item.url})")
    return "\n".join(lines)


async def send_alert(
    item: TargetItem,
    record: AlertRecord,
    bot_token: str,
    chat_id: str,
    history: list[PriceRecord] | None = None,
) -> bool:
    """
    Send a Telegram alert for *record*.
    If *history* has at least 2 readings, sends a photo with the price chart.
    Returns True if the API call succeeded, False otherwise.
    """
    if not bot_token or not chat_id:
        logger.warning("Telegram credentials not configured — skipping alert")
        return False

    text = _format_message(item, record)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if history and len(history) >= 2:
                from price_tracker.charts import build_item_graph
                from price_tracker.db.database import get_purchases
                purchases = get_purchases(item.item_id)
                img = build_item_graph(item, history, purchases)
                resp = await client.post(
                    _TELEGRAM_API.format(token=bot_token, method="sendPhoto"),
                    data={"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"},
                    files={"photo": ("chart.png", img, "image/png")},
                )
            else:
                resp = await client.post(
                    _TELEGRAM_API.format(token=bot_token, method="sendMessage"),
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": False,
                    },
                )
            resp.raise_for_status()
        logger.info("Telegram alert sent for %s", item.name)
        return True
    except httpx.HTTPError as exc:
        logger.error("Telegram send failed for %s: %s", item.name, exc)
        return False
