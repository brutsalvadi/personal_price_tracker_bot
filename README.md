# Personal Price Tracker Bot

A self-hosted Telegram bot that monitors product prices and alerts you when they drop. Runs as a systemd service on a Raspberry Pi or any Linux server.

## Features

- Tracks prices from any website — static pages (requests + BeautifulSoup) or JavaScript-rendered pages (Playwright/Chromium)
- Supports CSS selectors, XPath, and JSON-LD structured data
- Sends Telegram alerts with a price history chart when a price drops
- Telegram bot commands to list, add, remove, and check items on demand
- `/graph N` — price history chart for a single item
- `/graph all` — cumulative % variation chart for all tracked items
- `/bought N` — marks a purchase with a ★ on charts
- Stores history in a local TinyDB JSON file (no external DB needed)
- Deploys with a single `./deploy.sh` via rsync + systemd

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (package manager)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A Linux server for deployment (Raspberry Pi works great)

## Quick start

```bash
git clone https://github.com/brutsalvadi/personal_price_tracker_bot.git
cd personal_price_tracker_bot

cp .env.example .env        # fill in your Telegram credentials
uv sync

uv run python -m price_tracker --config targets.yaml
```

**Chromium** is required for JS-rendered pages. Two options:

- **System package (recommended for servers):** `sudo apt install chromium-browser`, then set `CHROMIUM_PATH=/usr/bin/chromium-browser` in `.env`
- **Playwright-bundled:** `playwright install chromium` — no `.env` change needed

## Configuration

Edit `targets.yaml` to define what to track:

```yaml
defaults:
  interval_minutes: 240
  alert_on: price_drop

targets:
  - name: Sony WH-1000XM5
    url: https://www.amazon.es/dp/B09XS7JWHH
    selector:
      - "#corePrice_desktop .a-offscreen"
      - ".a-price .a-offscreen"
    selector_type: css
    interval_minutes: 60
    threshold: 250.00       # alert when price drops below this
    alert_on: price_drop
    js_rendered: true       # true = Playwright, false = requests+BS4
    currency: EUR

  - name: Some Static Site Product
    url: https://example.com/product
    selector: offers.price  # dot-path into JSON-LD structured data
    selector_type: json_ld
    interval_minutes: 120
    alert_on: any_change
    js_rendered: false
    currency: EUR
```

### Selector types

| `selector_type` | How it works |
|-----------------|-------------|
| `css` | Standard CSS selector — list multiple as fallbacks |
| `xpath` | XPath expression |
| `json_ld` | Dot-path into the page's JSON-LD structured data (e.g. `offers.price`) |

### Alert modes

| `alert_on` | When it fires |
|------------|--------------|
| `price_drop` | When price drops below `threshold` (or any decrease if no threshold set) |
| `any_change` | Whenever the price differs from the previous reading |

## Bot commands

| Command | Description |
|---------|-------------|
| `/list` | Show tracked items with latest prices |
| `/check` | Immediately scrape all items |
| `/check N` | Immediately scrape one item |
| `/graph N` | Price history chart for item N |
| `/graph all` | Cumulative % change chart for all items |
| `/bought N` | Record a purchase (marks a ★ on charts) |
| `/add` | Add a new item (interactive) |
| `/remove N` | Stop tracking an item |
| `/help` | Show command list |

## Deploying to a server

### First time

```bash
# 1. On your local machine — push the code
./deploy.sh --setup

# 2. SSH into the server and run the installer
ssh user@yourserver.example.com
bash ~/src/price_tracking/install.sh

# 3. Fill in your Telegram credentials
nano ~/src/price_tracking/.env

# 4. Start the service
sudo systemctl start price-tracker
```

### Subsequent deploys

```bash
./deploy.sh
```

This rsyncs the code, runs `uv sync`, and restarts the systemd service. By default it pulls `targets.yaml` from the server first (since the bot can add/remove items at runtime). Use `--overwrite` to push your local version instead.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | — | Target chat/group ID |
| `DB_PATH` | `data/db.json` | TinyDB file path |
| `PID_FILE` | `data/price_tracker.pid` | PID file location |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `CHROMIUM_PATH` | _(unset)_ | Path to system Chromium, e.g. `/usr/bin/chromium-browser` |

## Running tests

```bash
uv run pytest
```

## Stack

- [APScheduler](https://github.com/agronholm/apscheduler) — job scheduling
- [Playwright](https://playwright.dev/python/) — headless Chromium for JS-rendered pages
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — HTML parsing
- [TinyDB](https://tinydb.readthedocs.io/) — lightweight JSON database
- [httpx](https://www.python-httpx.org/) — async HTTP (Telegram API)
- [matplotlib](https://matplotlib.org/) — price charts
- [python-dotenv](https://github.com/theskumar/python-dotenv) — env config
