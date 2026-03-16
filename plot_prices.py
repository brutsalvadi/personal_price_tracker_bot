"""
Cumulative price-variation chart.

Reads all price history from data/db.json and plots each product's price
as a percentage change relative to its first recorded price.

Usage:
    uv run python plot_prices.py
    uv run python plot_prices.py --db data/db.json --out chart.png
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from tinydb import TinyDB
from tinydb.storages import JSONStorage


def load_history(db_path: str) -> dict[str, list[tuple[datetime, float]]]:
    """Return {item_name: [(timestamp, price), ...]} sorted oldest-first."""
    db = TinyDB(db_path, storage=JSONStorage)
    rows = db.table("prices").all()
    db.close()

    by_item: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    for r in rows:
        ts = datetime.fromisoformat(r["scraped_at"].replace("Z", "+00:00"))
        by_item[r["item_name"]].append((ts, r["price"], r["item_id"]))

    return {
        name: sorted([(ts, price) for ts, price, _ in entries], key=lambda x: x[0])
        for name, entries in by_item.items()
    }


def plot(history: dict[str, list[tuple[datetime, float]]], out: str | None) -> None:
    if not history:
        print("No price data found in the database.")
        return

    fig, ax = plt.subplots(figsize=(12, 6))

    for name, records in history.items():
        if len(records) < 1:
            continue
        base_price = records[0][1]
        if base_price == 0:
            continue
        times = [ts for ts, _ in records]
        pct = [(price / base_price - 1) * 100 for _, price in records]
        ax.plot(times, pct, marker="o", markersize=3, linewidth=1.5, label=name)

    ax.axhline(0, color="grey", linewidth=0.8, linestyle="--")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.1f}%"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")

    ax.set_title("Price variation relative to first recorded price")
    ax.set_xlabel("Date")
    ax.set_ylabel("Change (%)")
    ax.legend(loc="best", fontsize="small")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    if out:
        fig.savefig(out, dpi=150)
        print(f"Chart saved to {out}")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot cumulative price variation")
    parser.add_argument("--db", default="data/db.json", help="Path to TinyDB file")
    parser.add_argument("--out", default=None, help="Save to file instead of showing")
    args = parser.parse_args()

    history = load_history(args.db)
    print(f"Found {len(history)} product(s): {', '.join(history)}")
    plot(history, args.out)


if __name__ == "__main__":
    main()
