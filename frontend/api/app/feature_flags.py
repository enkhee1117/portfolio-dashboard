"""Feature flag system — toggle features via config file or env var."""
import json
import os
import logging

logger = logging.getLogger("portfolio")

DEFAULT_FLAGS = {
    "wash_sales": True,
    "rsi_screener": True,
    "theme_baskets": True,
    "intraday_refresh": True,
    "recent_trades": True,
    "daily_movers": True,
}

_flags: dict = {}


def load_flags():
    global _flags
    config_path = os.path.join(os.path.dirname(__file__), "..", "feature_flags.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            _flags = {**DEFAULT_FLAGS, **json.load(f)}
    elif os.environ.get("FEATURE_FLAGS"):
        _flags = {**DEFAULT_FLAGS, **json.loads(os.environ["FEATURE_FLAGS"])}
    else:
        _flags = dict(DEFAULT_FLAGS)
    logger.info(f"Feature flags loaded: {_flags}")


def is_enabled(flag: str) -> bool:
    if not _flags:
        load_flags()
    return _flags.get(flag, False)


def get_all_flags() -> dict:
    if not _flags:
        load_flags()
    return dict(_flags)
