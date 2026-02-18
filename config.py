"""Configuration settings for GTA Newswire Tracker."""

# Rockstar Newswire URLs
NEWSWIRE_BASE_URL = "https://www.rockstargames.com/newswire"
NEWSWIRE_GTA_ONLINE_URL = f"{NEWSWIRE_BASE_URL}/tag/gta-online"

# Request settings
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Data paths
WISHLIST_FILE = "data/wishlist.json"

# Parsing settings
DISCOUNT_KEYWORDS = ["discount", "off", "% off", "sale", "bonus", "free"]
EVENT_KEYWORDS = ["event", "bonus", "double", "triple", "2x", "3x", "week"]
PODIUM_KEYWORDS = ["podium", "lucky wheel", "prize ride", "test track"]
