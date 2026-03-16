from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from price_tracker.bot import BotHandler
from price_tracker.config import Settings
from price_tracker.db.database import close_db
from price_tracker.scheduler import build_scheduler

logger = logging.getLogger(__name__)


def _write_pid_file(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    logger.debug("PID file written: %s (%d)", pid_file, os.getpid())


def _remove_pid_file(pid_file: Path) -> None:
    try:
        pid_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove PID file %s: %s", pid_file, exc)


def setup_logging(log_level: str) -> None:
    """
    Configure root logger.
    When running under systemd (JOURNAL_STREAM is set), omit timestamps because
    journald adds its own.
    """
    in_journal = "JOURNAL_STREAM" in os.environ
    fmt = "%(levelname)s %(name)s: %(message)s" if in_journal else "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=fmt,
        stream=sys.stdout,
    )


async def run(settings: Settings) -> None:
    shutdown_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        logger.info("Received signal %s — initiating shutdown", signal.Signals(sig).name)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    scheduler = build_scheduler(settings)
    scheduler.start()
    logger.info("Scheduler started with %d job(s)", len(scheduler.get_jobs()))

    bot = BotHandler(settings, scheduler)
    bot_task = asyncio.create_task(bot.start_polling(), name="bot-polling")

    try:
        await shutdown_event.wait()
    finally:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        logger.info("Shutting down scheduler…")
        scheduler.shutdown(wait=True)
        close_db()
        _remove_pid_file(settings.pid_file)
        logger.info("Shutdown complete")
