from __future__ import annotations

import argparse
import asyncio
import sys

from price_tracker.config import load_settings
from price_tracker.daemon import _write_pid_file, run, setup_logging


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="price_tracker",
        description="Price tracking daemon with Telegram alerts",
    )
    parser.add_argument(
        "--config",
        default="targets.yaml",
        metavar="FILE",
        help="Path to targets.yaml (default: targets.yaml)",
    )
    parser.add_argument(
        "--env",
        default=".env",
        metavar="FILE",
        help="Path to .env file (default: .env)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        settings = load_settings(config_path=args.config, env_path=args.env)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(settings.log_level)

    _write_pid_file(settings.pid_file)

    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
