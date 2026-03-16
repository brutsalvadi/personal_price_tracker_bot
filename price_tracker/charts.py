"""Chart rendering helpers shared between bot.py and notifier.py."""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from price_tracker.models import PriceRecord, PurchaseRecord, TargetItem


def build_item_graph(
    item: TargetItem,
    history: list[PriceRecord],
    purchases: list[PurchaseRecord] | None = None,
) -> bytes:
    """Render a price-history line chart for a single item. Returns PNG bytes."""
    timestamps = [
        datetime.strptime(r.scraped_at, "%Y-%m-%dT%H:%M:%SZ") for r in history
    ]
    prices = [r.price for r in history]
    currency = history[0].currency

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(timestamps, prices, marker="o", markersize=4, linewidth=1.5, color="#2196F3")

    if purchases:
        px = [datetime.strptime(p.bought_at, "%Y-%m-%dT%H:%M:%SZ") for p in purchases]
        py = [p.price for p in purchases]
        ax.scatter(px, py, marker="*", s=200, color="#FF9800", zorder=5, label="Bought")
        ax.legend(fontsize=9)

    if item.threshold is not None:
        ax.axhline(
            item.threshold,
            color="#F44336",
            linestyle="--",
            linewidth=1,
            label=f"Threshold {item.threshold:.2f} {currency}",
        )
        ax.legend(fontsize=9)

    span_days = (timestamps[-1] - timestamps[0]).days
    if span_days <= 2:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))
    elif span_days <= 30:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.set_title(item.name, fontsize=12, pad=10)
    ax.set_ylabel(currency, fontsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.margins(x=0.02)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def build_group_graph(
    group_id: str,
    all_history: list[tuple[TargetItem, list[PriceRecord]]],
    all_purchases: dict[str, list[PurchaseRecord]] | None = None,
) -> bytes:
    """Render absolute prices for all items in a group. Returns PNG bytes."""
    fig, ax = plt.subplots(figsize=(12, 5))

    currencies = {history[0].currency for _, history in all_history if history}
    ylabel = next(iter(currencies)) if len(currencies) == 1 else "Price"

    all_timestamps = []
    for item, history in all_history:
        if not history:
            continue
        timestamps = [datetime.strptime(r.scraped_at, "%Y-%m-%dT%H:%M:%SZ") for r in history]
        prices = [r.price for r in history]
        all_timestamps.extend(timestamps)
        line, = ax.plot(timestamps, prices, marker="o", markersize=4, linewidth=1.5, label=item.name)

        if item.threshold is not None:
            ax.axhline(item.threshold, color=line.get_color(), linestyle="--", linewidth=0.8, alpha=0.6)

        if all_purchases:
            for p in all_purchases.get(item.item_id, []):
                pt = datetime.strptime(p.bought_at, "%Y-%m-%dT%H:%M:%SZ")
                ax.scatter(pt, p.price, marker="*", s=200, color=line.get_color(), zorder=5)

    if all_timestamps:
        span_days = (max(all_timestamps) - min(all_timestamps)).days
        if span_days <= 2:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))
        elif span_days <= 30:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.set_title(f"Group {group_id} — price history", fontsize=12, pad=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))
    ax.legend(loc="best", fontsize="small")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.margins(x=0.02)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def build_all_graph(
    all_history: list[tuple[TargetItem, list[PriceRecord]]],
    all_purchases: dict[str, list[PurchaseRecord]] | None = None,
) -> bytes:
    """Render cumulative % change (vs first reading) for all items. Returns PNG bytes."""
    fig, ax = plt.subplots(figsize=(12, 5))

    for item, history in all_history:
        if not history:
            continue
        base = history[0].price
        if base == 0:
            continue
        timestamps = [
            datetime.strptime(r.scraped_at, "%Y-%m-%dT%H:%M:%SZ") for r in history
        ]
        pct = [(r.price / base - 1) * 100 for r in history]
        line, = ax.plot(timestamps, pct, marker="o", markersize=3, linewidth=1.5, label=item.name)

        if all_purchases:
            for p in all_purchases.get(item.item_id, []):
                pt = datetime.strptime(p.bought_at, "%Y-%m-%dT%H:%M:%SZ")
                pp = (p.price / base - 1) * 100
                ax.scatter(pt, pp, marker="*", s=200, color=line.get_color(), zorder=5)

    ax.axhline(0, color="grey", linewidth=0.8, linestyle="--")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.1f}%"))

    all_timestamps = [
        datetime.strptime(r.scraped_at, "%Y-%m-%dT%H:%M:%SZ")
        for _, history in all_history
        for r in history
    ]
    if all_timestamps:
        span_days = (max(all_timestamps) - min(all_timestamps)).days
        if span_days <= 2:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %H:%M"))
        elif span_days <= 30:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    fig.autofmt_xdate(rotation=30, ha="right")

    ax.set_title("Price variation — all products (% vs first reading)", fontsize=12, pad=10)
    ax.set_ylabel("Change (%)", fontsize=10)
    ax.legend(loc="best", fontsize="small")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.margins(x=0.02)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
