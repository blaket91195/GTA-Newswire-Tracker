"""Configuration settings for GTA Newswire Tracker."""

# Rockstar Newswire URLs
NEWSWIRE_BASE_URL = "https://www.rockstargames.com/newswire"

# Tag IDs for filtering newswire articles
TAG_GTA_ONLINE = 702

# Request settings
REQUEST_TIMEOUT = 30  # seconds

# Data paths
WISHLIST_FILE = "data/wishlist.json"
PRICES_FILE = "data/prices.json"

# Debug: save raw API JSON responses to data/cache/
DEBUG_CACHE = False

# Parsing settings
DISCOUNT_KEYWORDS = ["discount", "off", "% off", "sale", "bonus", "free"]
EVENT_KEYWORDS = ["event", "bonus", "double", "triple", "2x", "3x", "week"]
PODIUM_KEYWORDS = ["podium", "lucky wheel", "prize ride", "test track"]
