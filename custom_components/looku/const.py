"""Constants for the Looku integration."""

from datetime import timedelta

DOMAIN = "looku"
SCAN_INTERVAL = timedelta(minutes=10)

# Options
CONF_RANGE = "range"
RANGES = ["24h", "7d", "28d", "3m", "12m"]
DEFAULT_RANGE = "7d"

# Modules whose reports have sensors.
MODULE_SHOP = "shop"
