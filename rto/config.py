"""Loads and saves config/rules.yaml - the file ops people edit.

Rules are re-read whenever the file changes, so edits apply to the next order
without restarting anything. Saving keeps the comments in the file.
"""
from __future__ import annotations

import copy
import os
import threading
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = Path(os.getenv("RTO_RULES_PATH", ROOT / "config" / "rules.yaml"))
MODEL_PATH = ROOT / "config" / "risk_model.json"
DATA_DIR = ROOT / "data"
RAW_CSV = DATA_DIR / "raw" / "orders_sample.csv"
CLEAN_CSV = DATA_DIR / "orders_clean.csv"
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
DB_PATH = Path(os.getenv("RTO_DB_PATH", DATA_DIR / "app.db"))

_yaml = YAML()
_yaml.preserve_quotes = True
_lock = threading.Lock()
_cache: dict = {"mtime": None, "rules": None}

ACTIONS = ("ship", "confirm", "nudge", "hold")
ACTION_LABELS = {
    "ship": "Ship as-is",
    "confirm": "Ship after confirmation",
    "nudge": "Nudge to prepaid",
    "hold": "Hold / cancel",
}


def _to_plain(node):
    if isinstance(node, dict):
        return {str(k): _to_plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_to_plain(v) for v in node]
    return node


def load_rules(path: Path | None = None) -> dict:
    """Return the rules as a plain dict, re-reading the file only if it changed."""
    path = Path(path or RULES_PATH)
    with _lock:
        mtime = path.stat().st_mtime
        if _cache.get("path") == path and _cache["mtime"] == mtime:
            return copy.deepcopy(_cache["rules"])
        with open(path, encoding="utf-8") as f:
            rules = _to_plain(_yaml.load(f))
        validate_rules(rules)
        _cache.update(path=path, mtime=mtime, rules=rules)
        return copy.deepcopy(rules)


def validate_rules(rules: dict) -> None:
    """Raise ValueError with a plain-English message if the rules don't make sense."""
    t = rules["thresholds"]
    n, c, h = t["nudge_from_risk_pct"], t["confirm_from_risk_pct"], t["hold_from_risk_pct"]
    for name, v in t.items():
        if not 0 <= v <= 100:
            raise ValueError(f"{name} must be between 0 and 100 (got {v})")
    if not n <= c <= h:
        raise ValueError(
            f"Thresholds must go up in order: nudge ({n}) <= confirm ({c}) <= hold ({h})"
        )
    for section in ("money", "assumptions"):
        for name, v in rules[section].items():
            if not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f"{section}.{name} must be a number of 0 or more (got {v})")
    for name, v in rules["assumptions"].items():
        if v > 100:
            raise ValueError(f"assumptions.{name} is a percentage, so it must be 100 or less")
    for name in ("damaged_return_pct", "gross_margin_pct", "prepaid_rto_pct"):
        if rules["money"][name] > 100:
            raise ValueError(f"money.{name} is a percentage, so it must be 100 or less")
    w = rules["whatsapp"]
    if w["confirm_no_reply_action"] not in ("cancel", "ship"):
        raise ValueError("whatsapp.confirm_no_reply_action must be 'cancel' or 'ship'")
    if w["hold_no_reply_action"] not in ("cancel", "ship"):
        raise ValueError("whatsapp.hold_no_reply_action must be 'cancel' or 'ship'")
    if not 0 < w["reminder_after_hours"] < w["give_up_after_hours"]:
        raise ValueError("whatsapp.reminder_after_hours must be less than give_up_after_hours")


def save_rules(updates: dict, path: Path | None = None) -> dict:
    """Merge `updates` ({section: {key: value}}) into the file, keeping its comments."""
    path = Path(path or RULES_PATH)
    with _lock:
        with open(path, encoding="utf-8") as f:
            doc = _yaml.load(f)
        for section, values in updates.items():
            if section not in doc:
                raise ValueError(f"Unknown settings section: {section}")
            for key, value in values.items():
                if key not in doc[section]:
                    raise ValueError(f"Unknown setting: {section}.{key}")
                old = doc[section][key]
                if isinstance(old, bool):
                    value = bool(value)
                elif isinstance(old, int) and isinstance(value, float) and value.is_integer():
                    value = int(value)
                doc[section][key] = value
        validate_rules(_to_plain(doc))
        with open(path, "w", encoding="utf-8") as f:
            _yaml.dump(doc, f)
        _cache["mtime"] = None
    return load_rules(path)
