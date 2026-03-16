from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from price_tracker.models import TargetItem

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    db_path: Path
    pid_file: Path
    log_level: str
    targets: list[TargetItem]
    groups: dict[str, list[str]]        # group_id → [item_id, ...]
    config_path: Path = Path("targets.yaml")


def _as_selector_list(value: str | list) -> list[str]:
    """Accept a plain string or a YAML list and always return list[str]."""
    if isinstance(value, list):
        return [str(s) for s in value]
    return [str(value)]


def _item_id(name: str, url: str) -> str:
    """Deterministic 12-char hex ID derived from name + URL."""
    digest = hashlib.sha256(f"{name}|{url}".encode()).hexdigest()
    return digest[:12]


def load_settings(
    config_path: str | Path = "targets.yaml",
    env_path: str | Path = ".env",
) -> Settings:
    load_dotenv(env_path)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    db_path = Path(os.environ.get("DB_PATH", "data/db.json"))
    pid_file = Path(os.environ.get("PID_FILE", "data/price_tracker.pid"))
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"targets.yaml not found: {config_path}")

    with config_path.open() as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    defaults = raw.get("defaults", {})
    default_interval = int(defaults.get("interval_minutes", 60))
    default_alert_on = defaults.get("alert_on", "price_drop")

    targets: list[TargetItem] = []
    for entry in raw.get("targets", []):
        name = entry["name"]
        url = entry["url"]
        targets.append(
            TargetItem(
                name=name,
                url=url,
                selector=_as_selector_list(entry["selector"]),
                item_id=_item_id(name, url),
                selector_type=entry.get("selector_type", "css"),
                interval_minutes=int(entry.get("interval_minutes", default_interval)),
                threshold=float(entry["threshold"]) if "threshold" in entry else None,
                alert_on=entry.get("alert_on", default_alert_on),
                js_rendered=bool(entry.get("js_rendered", False)),
                currency=entry.get("currency", "EUR"),
            )
        )

    # Load groups: {group_id: [item_id, ...]}
    groups: dict[str, list[str]] = {
        k.upper(): list(v)
        for k, v in raw.get("groups", {}).items()
    }

    logger.info("Loaded %d target(s) from %s", len(targets), config_path)
    return Settings(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        db_path=db_path,
        pid_file=pid_file,
        log_level=log_level,
        targets=targets,
        groups=groups,
        config_path=config_path,
    )


def add_target_to_yaml(item: TargetItem, config_path: Path) -> None:
    """Append *item* to the targets list in targets.yaml."""
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)

    selector_value = item.selector[0] if len(item.selector) == 1 else item.selector
    entry: dict = {
        "name": item.name,
        "url": item.url,
        "selector": selector_value,
        "selector_type": item.selector_type,
        "interval_minutes": item.interval_minutes,
        "alert_on": item.alert_on,
        "js_rendered": item.js_rendered,
        "currency": item.currency,
    }
    if item.threshold is not None:
        entry["threshold"] = item.threshold

    raw.setdefault("targets", []).append(entry)
    with config_path.open("w") as fh:
        yaml.dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("Wrote new target %r to %s", item.name, config_path)


def update_threshold_in_yaml(item_id: str, threshold: float | None, config_path: Path) -> None:
    """Set or clear the threshold for *item_id* in targets.yaml."""
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)
    for entry in raw.get("targets", []):
        if _item_id(entry["name"], entry["url"]) == item_id:
            if threshold is None:
                entry.pop("threshold", None)
                entry["alert_on"] = "any_change"
            else:
                entry["threshold"] = threshold
                entry["alert_on"] = "price_drop"
            break
    with config_path.open("w") as fh:
        yaml.dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _save_groups(groups: dict[str, list[str]], config_path: Path) -> None:
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)
    if groups:
        raw["groups"] = {k: v for k, v in sorted(groups.items())}
    else:
        raw.pop("groups", None)
    with config_path.open("w") as fh:
        yaml.dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)


def add_to_group(group_id: str, item_id: str, groups: dict[str, list[str]], config_path: Path) -> None:
    gid = group_id.upper()
    if item_id not in groups.get(gid, []):
        groups.setdefault(gid, []).append(item_id)
    _save_groups(groups, config_path)


def remove_from_group(group_id: str, item_id: str, groups: dict[str, list[str]], config_path: Path) -> None:
    gid = group_id.upper()
    if gid in groups:
        groups[gid] = [i for i in groups[gid] if i != item_id]
        if not groups[gid]:
            del groups[gid]
    _save_groups(groups, config_path)


def delete_group(group_id: str, groups: dict[str, list[str]], config_path: Path) -> None:
    groups.pop(group_id.upper(), None)
    _save_groups(groups, config_path)


def remove_target_from_yaml(item_id: str, config_path: Path) -> None:
    """Remove the item with *item_id* from targets.yaml."""
    with config_path.open() as fh:
        raw = yaml.safe_load(fh)

    before = len(raw.get("targets", []))
    raw["targets"] = [
        t for t in raw.get("targets", [])
        if _item_id(t["name"], t["url"]) != item_id
    ]
    with config_path.open("w") as fh:
        yaml.dump(raw, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info(
        "Removed %d target(s) from %s", before - len(raw["targets"]), config_path
    )
