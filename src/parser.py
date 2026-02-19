"""Fetch and parse GTA Online newswire article content.

The GraphQL API provides article metadata (title, date, image) but not
the full body text.  This module fetches individual article pages,
extracts the body content, and parses out discounts, bonuses, and the
podium/prize vehicle using regex patterns.
"""

import hashlib
import json
import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request settings
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

CACHE_DIR = os.path.join("data", "cache")

# ---------------------------------------------------------------------------
# Article fetching & caching
# ---------------------------------------------------------------------------


def _cache_path(url):
    """Return the cache file path for a given URL."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"article_{url_hash}.html")


def _load_cached(url):
    """Load cached HTML for a URL if it exists."""
    path = _cache_path(url)
    if os.path.exists(path):
        logger.debug("Cache hit: %s", path)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _save_cache(url, html):
    """Save HTML to the cache directory."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(url)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.debug("Cached article: %s", path)


def fetch_article_content(article_url):
    """Fetch an article page and extract the main body text.

    Caches the raw HTML in data/cache/ to avoid re-fetching during
    development.  On failure returns None.

    Args:
        article_url: Full URL, e.g.
            "https://www.rockstargames.com/newswire/article/..."

    Returns:
        Cleaned article body text (str), or None on error.
    """
    # Check cache first
    cached = _load_cached(article_url)
    if cached is not None:
        logger.info("Using cached article: %s", article_url)
        return _extract_body_text(cached)

    # Fetch with retry
    last_error = None
    for attempt in range(1, 4):
        logger.info("Fetching article (attempt %d/3): %s", attempt, article_url)
        try:
            resp = requests.get(
                article_url,
                headers=_HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.Timeout as exc:
            last_error = exc
            logger.warning("Timeout (attempt %d/3)", attempt)
            if attempt < 3:
                time.sleep(2 ** attempt)
            continue
        except requests.ConnectionError as exc:
            last_error = exc
            logger.warning("Connection error (attempt %d/3): %s", attempt, exc)
            if attempt < 3:
                time.sleep(2 ** attempt)
            continue
        except requests.HTTPError as exc:
            status = resp.status_code
            logger.error("HTTP %d fetching article", status)
            if status == 404:
                logger.error("Article not found: %s", article_url)
                return None
            last_error = exc
            if 400 <= status < 500:
                return None
            if attempt < 3:
                time.sleep(2 ** attempt)
            continue

        html = resp.text
        _save_cache(article_url, html)
        return _extract_body_text(html)

    logger.error("All 3 attempts failed for %s. Last error: %s", article_url, last_error)
    return None


def _extract_body_text(html):
    """Extract the readable body text from article HTML.

    Rockstar's site is JS-heavy — the HTML is often a thin shell with
    an empty ``<body>`` and all content loaded via JavaScript.  We try
    several strategies in order of reliability:

    1. CSS selectors for known article-body containers.
    2. Embedded JSON state (``__NEXT_DATA__``, ``window.__DATA__``).
    3. Open Graph / Twitter meta-tag descriptions — these always
       contain a usable summary even when the body is empty.

    Args:
        html: Raw HTML string.

    Returns:
        Article body text string.
    """
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: Look for common article body containers
    body = (
        soup.select_one("div.article-body")
        or soup.select_one("div.post-body")
        or soup.select_one("article")
        or soup.select_one("div[class*='ArticleBody']")
        or soup.select_one("div[class*='article-content']")
        or soup.select_one("div.content-block")
        or soup.select_one("main")
    )

    if body is not None and len(body.get_text(strip=True)) >= 100:
        return body.get_text(separator="\n", strip=True)

    # Strategy 2: Look for JSON embedded in a <script> tag
    for script in soup.find_all("script"):
        script_text = script.string or ""
        if "__NEXT_DATA__" in script_text or '"body"' in script_text:
            json_text = _extract_json_body(script_text)
            if json_text and len(json_text) > 100:
                return json_text

    # Strategy 3: Extract from Open Graph / Twitter meta tags.
    # Rockstar's HTML shell always includes og:description and
    # twitter:description with a useful article summary.
    meta_text = _extract_meta_description(soup)
    if meta_text and len(meta_text) > 50:
        logger.info("Using meta-tag description (%d chars)", len(meta_text))
        return meta_text

    # Last resort: whatever text the <body> contains
    body_el = soup.find("body") or soup
    text = body_el.get_text(separator="\n", strip=True)
    return text


def _extract_meta_description(soup):
    """Build article text from Open Graph / Twitter meta tags.

    Rockstar's server-rendered HTML includes rich meta tags even though
    the ``<body>`` is empty.  We combine the title and description to
    produce a short but parseable article summary.

    Returns:
        Combined title + description string, or None.
    """
    # Gather the best title
    title = None
    # Rockstar uses property= for both OG and Twitter meta tags
    for attrs in [
        {"property": "og:title"},
        {"property": "twitter:title"},
        {"name": "twitter:title"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            title = tag["content"].strip()
            break
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    # Always strip the " - Rockstar Games" suffix
    if title:
        title = title.rsplit(" - Rockstar Games", 1)[0].strip()

    # Gather the best description
    description = None
    for attrs in [
        {"property": "og:description"},
        {"property": "twitter:description"},
        {"name": "twitter:description"},
        {"name": "description"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = tag["content"].strip()
            break

    if not title and not description:
        return None

    parts = []
    if title:
        parts.append(title)
    if description:
        parts.append(description)
    return "\n".join(parts)


def _extract_json_body(script_text):
    """Try to extract article body from embedded JSON in script tags."""
    # Try to find JSON object
    for marker in ["__NEXT_DATA__", "window.__DATA__"]:
        idx = script_text.find(marker)
        if idx == -1:
            continue
        # Find the JSON start
        json_start = script_text.find("{", idx)
        if json_start == -1:
            continue
        try:
            data = json.loads(script_text[json_start:])
            return _find_body_in_json(data)
        except (json.JSONDecodeError, ValueError):
            pass

    # Direct JSON attempt (some scripts are pure JSON)
    try:
        data = json.loads(script_text.strip())
        return _find_body_in_json(data)
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _find_body_in_json(data, depth=0):
    """Recursively search a JSON structure for article body content."""
    if depth > 10:
        return None

    if isinstance(data, dict):
        # Look for common body field names
        for key in ("body", "content", "articleBody", "article_body", "rawBody"):
            if key in data and isinstance(data[key], str) and len(data[key]) > 100:
                # Strip HTML tags from the body if present
                soup = BeautifulSoup(data[key], "lxml")
                return soup.get_text(separator="\n", strip=True)

        for value in data.values():
            result = _find_body_in_json(value, depth + 1)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_body_in_json(item, depth + 1)
            if result:
                return result

    return None


# ---------------------------------------------------------------------------
# Discount parsing
# ---------------------------------------------------------------------------

# "40% off the Oppressor Mk II", "30% off all Weaponized Vehicles"
_RE_DISCOUNT_OFF = re.compile(
    r"(\d{1,2})%\s+off\s+(?:the\s+|all\s+)?(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "Oppressor Mk II – 30% off", "Nightclub — 40% off"
_RE_DISCOUNT_ITEM_FIRST = re.compile(
    r"([^.\n]+?)\s*[–—\-]+\s*(\d{1,2})%\s+off",
    re.IGNORECASE,
)

# "30% discount on the Oppressor Mk II"
_RE_DISCOUNT_ON = re.compile(
    r"(\d{1,2})%\s+discount\s+on\s+(?:the\s+|all\s+)?(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "Oppressor Mk II (30% off)"
_RE_DISCOUNT_PAREN = re.compile(
    r"([^.\n]+?)\s*\((\d{1,2})%\s+(?:off|discount)\)",
    re.IGNORECASE,
)

# "reduced by 40%"
_RE_DISCOUNT_REDUCED = re.compile(
    r"([^.\n]+?)\s+reduced\s+by\s+(\d{1,2})%",
    re.IGNORECASE,
)

# "40 percent off the Oppressor"
_RE_DISCOUNT_PERCENT_WORD = re.compile(
    r"(\d{1,2})\s+percent\s+off\s+(?:the\s+|all\s+)?(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# Vehicle category hints (used to tag category when possible)
_VEHICLE_HINTS = [
    "car", "vehicle", "bike", "motorcycle", "helicopter", "plane",
    "aircraft", "boat", "jet", "truck", "suv", "sports", "super",
    "muscle", "sedan", "coupe", "compact", "off-road", "van",
]
_PROPERTY_HINTS = [
    "apartment", "garage", "office", "nightclub", "arcade", "facility",
    "bunker", "hangar", "clubhouse", "warehouse", "agency", "auto shop",
    "property", "penthouse",
]
_WEAPON_HINTS = [
    "weapon", "gun", "rifle", "pistol", "shotgun", "smg", "mg",
    "sniper", "launcher", "melee", "throwable", "mk ii",
]


def _guess_category(item_name, surrounding_text=""):
    """Guess the discount item category from its name or context."""
    combined = (item_name + " " + surrounding_text).lower()
    if any(h in combined for h in _WEAPON_HINTS):
        return "weapon"
    if any(h in combined for h in _PROPERTY_HINTS):
        return "property"
    if any(h in combined for h in _VEHICLE_HINTS):
        return "vehicle"
    return "other"


def _clean(text):
    """Strip trailing punctuation and whitespace."""
    return text.strip().rstrip(".,;:–—-").strip()


def parse_discounts(article_text):
    """Extract percentage discounts and item names from article text.

    Args:
        article_text: Cleaned article body text.

    Returns:
        List of dicts: [{"item": "Oppressor Mk II", "discount": "40%", "category": "vehicle"}]
    """
    if not article_text:
        return []

    discounts = []
    seen = set()

    # Patterns where percentage comes first
    for pattern in [_RE_DISCOUNT_OFF, _RE_DISCOUNT_ON, _RE_DISCOUNT_PERCENT_WORD]:
        for match in pattern.finditer(article_text):
            pct = match.group(1) + "%"
            item = _clean(match.group(2))
            key = item.lower()
            if item and key not in seen and len(item) > 2:
                seen.add(key)
                discounts.append({
                    "item": item,
                    "discount": pct,
                    "category": _guess_category(item),
                })

    # Patterns where item comes first
    for pattern in [_RE_DISCOUNT_ITEM_FIRST, _RE_DISCOUNT_PAREN, _RE_DISCOUNT_REDUCED]:
        for match in pattern.finditer(article_text):
            item = _clean(match.group(1))
            pct = match.group(2) + "%"
            key = item.lower()
            if item and key not in seen and len(item) > 2:
                seen.add(key)
                discounts.append({
                    "item": item,
                    "discount": pct,
                    "category": _guess_category(item),
                })

    return discounts


# ---------------------------------------------------------------------------
# Bonus / multiplier parsing
# ---------------------------------------------------------------------------

_MULTIPLIER_MAP = {
    "double": "2X",
    "triple": "3X",
    "quadruple": "4X",
}


def _normalise_multiplier(raw):
    """Convert 'Double'/'Triple' words to '2X'/'3X' form."""
    lower = raw.lower().strip()
    if lower in _MULTIPLIER_MAP:
        return _MULTIPLIER_MAP[lower]
    return raw.upper().strip()


# "2X GTA$ and RP on Cayo Perico Heist"
_RE_MULT_EXPLICIT = re.compile(
    r"(\d)[Xx]\s+GTA\$?\s*(?:and|&)\s*RP\s+(?:on|in|from)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "3X Rewards on Bunker Sales"
_RE_MULT_REWARDS = re.compile(
    r"(\d)[Xx]\s+(?:Rewards?|GTA\$?|RP)\s+(?:on|in|from|for)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "2X on Special Cargo"
_RE_MULT_SHORT = re.compile(
    r"(\d)[Xx]\s+(?:on|in|from)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "Double GTA$ and RP on Contact Missions"
_RE_WORD_MULT = re.compile(
    r"(Double|Triple|Quadruple)\s+(?:Rewards?|GTA\$?\s*(?:and|&)\s*RP|payouts?|earnings?)"
    r"\s+(?:on|in|from|for)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "Triple Rewards on Deadline Duet"
_RE_WORD_MULT_SHORT = re.compile(
    r"(Double|Triple|Quadruple)\s+(?:on|in|from|for)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# "Contact Missions paying out Double this week"
_RE_ACTIVITY_PAYING = re.compile(
    r"(.+?)\s+(?:paying out|offering|featuring)\s+(Double|Triple|Quadruple|\d[Xx])",
    re.IGNORECASE,
)

# "4x GTA$ on Associate and Bodyguard Salaries"
_RE_MULT_GTA_ONLY = re.compile(
    r"(\d)[Xx]\s+GTA\$?\s+(?:on|in|from|for)\s+(.+?)(?:\.|,\s|\n|$)",
    re.IGNORECASE,
)

# Reversed: "Deadline Duet Mode for Triple Rewards"
# Activity comes BEFORE the multiplier word.  The optional prefixes
# (in, the, new) are consumed outside the capture group so that only
# the activity name is captured.
_RE_REVERSED_MULT = re.compile(
    r"(?:in\s+)?(?:the\s+)?(?:new\s+)?(\w{3,}(?:\s+\w+){0,3}?)"
    r"\s+(?:Mode\s+)?(?:for|with)\s+"
    r"(Double|Triple|Quadruple)\s+(?:Rewards?|GTA\$?\s*(?:and|&)\s*RP|payouts?)",
    re.IGNORECASE,
)

# Trailing time phrases to strip from activity names
_RE_TRAILING_TIME = re.compile(
    r"\s+(?:this|next|the\s+next|all|every)\s+"
    r"(?:week|weeks|month|weekend|two\s+weeks)\s*$",
    re.IGNORECASE,
)

# If the entire activity (after stripping) is just a time reference, skip it
_RE_ONLY_TIME = re.compile(
    r"^(?:the\s+)?(?:next|this|all)?\s*(?:week|weeks|days?|hours?|month|today|weekend|two\s+weeks)$",
    re.IGNORECASE,
)


def parse_bonuses(article_text):
    """Extract 2X/3X/Double/Triple bonus events from article text.

    Args:
        article_text: Cleaned article body text.

    Returns:
        List of strings describing each bonus activity.
        Example: ["2X GTA$ & RP on Cayo Perico Heist", "3X on Bunker Sales"]
    """
    if not article_text:
        return []

    bonuses = []
    seen = set()

    def _add(mult, activity):
        activity = _clean(activity)
        if not activity or len(activity) < 3:
            return
        # Strip trailing time phrases: "Deadline Duet this week" → "Deadline Duet"
        activity = _RE_TRAILING_TIME.sub("", activity).strip()
        # Strip leading articles: "the Cayo Perico" → "Cayo Perico"
        activity = re.sub(r"^(?:the|a|an)\b\s*", "", activity, flags=re.IGNORECASE).strip()
        if not activity or len(activity) < 3:
            return
        # Skip if the entire remaining text is just a time reference
        if _RE_ONLY_TIME.match(activity):
            return
        key = activity.lower()
        if key not in seen:
            seen.add(key)
            bonuses.append(f"{mult} on {activity}")

    # Numeric patterns: "2X GTA$ and RP on ...", "3X Rewards on ...", etc.
    for pattern in [_RE_MULT_EXPLICIT, _RE_MULT_REWARDS, _RE_MULT_GTA_ONLY, _RE_MULT_SHORT]:
        for match in pattern.finditer(article_text):
            _add(match.group(1) + "X", match.group(2))

    # Word patterns: "Double/Triple Rewards on ..."
    for pattern in [_RE_WORD_MULT, _RE_WORD_MULT_SHORT]:
        for match in pattern.finditer(article_text):
            _add(_normalise_multiplier(match.group(1)), match.group(2))

    # Reversed: "Deadline Duet for Triple Rewards"
    for match in _RE_REVERSED_MULT.finditer(article_text):
        activity = match.group(1)
        mult = _normalise_multiplier(match.group(2))
        _add(mult, activity)

    # Activity-first: "Contact Missions paying out Double"
    for match in _RE_ACTIVITY_PAYING.finditer(article_text):
        _add(_normalise_multiplier(match.group(2)), match.group(1))

    return bonuses


# ---------------------------------------------------------------------------
# Podium / Prize Ride parsing
# ---------------------------------------------------------------------------

_PODIUM_PATTERNS = [
    # "Prize Ride: Grotti Turismo Classic"
    re.compile(r"Prize\s+Ride[\s:–—\-]+(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "Podium Vehicle: Grotti Turismo Classic"
    re.compile(r"Podium\s+Vehicle[\s:–—\-]+(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "Prize Ride this week is the Grotti Turismo Classic"
    re.compile(r"Prize\s+Ride\s+(?:this\s+week\s+)?is\s+(?:the\s+)?(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "Podium Vehicle this week is the Grotti Turismo Classic"
    re.compile(r"Podium\s+Vehicle\s+(?:this\s+week\s+)?is\s+(?:the\s+)?(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "Lucky Wheel: Grotti Turismo Classic"
    re.compile(r"Lucky\s+Wheel[\s:–—\-]+(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "Test Track: Grotti Turismo Classic"
    re.compile(r"Test\s+Track[\s:–—\-]+(?:the\s+)?(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE),
    # "spin the Lucky Wheel ... win the [vehicle]"
    re.compile(r"Lucky\s+Wheel.*?win\s+(?:the\s+|a\s+)?(.+?)(?:\.|,\s|\n|$)", re.IGNORECASE | re.DOTALL),
    # "[vehicle] as this week's Podium Vehicle / Prize Ride" (common in meta descriptions)
    re.compile(r"(?:the\s+)(\S+(?:\s+\S+){0,4}?)\s+as\s+(?:this\s+week'?s?\s+)?(?:the\s+)?(?:Podium\s+Vehicle|Prize\s+Ride|Test\s+Track)", re.IGNORECASE),
]


def parse_podium_vehicle(article_text):
    """Extract the podium/prize ride/test track vehicle name.

    Args:
        article_text: Cleaned article body text.

    Returns:
        Vehicle name string, or None if not found.
    """
    if not article_text:
        return None

    for pattern in _PODIUM_PATTERNS:
        match = pattern.search(article_text)
        if match:
            vehicle = _clean(match.group(1))
            if vehicle and len(vehicle) > 2:
                return vehicle

    return None


# ---------------------------------------------------------------------------
# Combined parser
# ---------------------------------------------------------------------------


def parse_full_article(article_url, blurb=""):
    """Fetch an article and parse all GTA Online weekly info from it.

    Combines fetch_article_content(), parse_discounts(),
    parse_bonuses(), and parse_podium_vehicle() into a single call.

    Args:
        article_url: Full URL to a Rockstar Newswire article.
        blurb: Optional extra text from the GraphQL API response
            (body/blurb/subtitle). Appended to the fetched article text
            to improve parsing coverage.

    Returns:
        Dict with keys:
            - discounts:      list of {"item": ..., "discount": ..., "category": ...}
            - bonuses:        list of bonus description strings
            - podium_vehicle: str or None
            - raw_text:       str (the extracted body text, for debugging)
        Returns None if the article could not be fetched.
    """
    text = fetch_article_content(article_url)
    if text is None:
        logger.error("Could not fetch article content: %s", article_url)
        return None

    # Supplement with any blurb text from the API
    if blurb:
        text = text + "\n" + blurb

    result = {
        "discounts": parse_discounts(text),
        "bonuses": parse_bonuses(text),
        "podium_vehicle": parse_podium_vehicle(text),
        "raw_text": text,
    }

    logger.info(
        "Parsed article: %d discounts, %d bonuses, podium=%s",
        len(result["discounts"]),
        len(result["bonuses"]),
        result["podium_vehicle"] or "none",
    )

    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_parser():
    """Test the parser against the latest weekly update article.

    Fetches the most recent weekly update URL from the scraper and
    runs all parsing functions against it.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Import here to avoid circular imports
    from src.scraper import get_latest_weekly_update

    print("=" * 60)
    print("  GTA Newswire Tracker — Parser Test")
    print("=" * 60)

    # Step 1: Get the latest weekly update URL
    print("\n[Step 1] Finding latest weekly update article...")
    weekly = get_latest_weekly_update()
    if weekly is None:
        print("  FAIL: Could not find a weekly update article.")
        return False

    print(f"  Title: {weekly['title']}")
    print(f"  Date:  {weekly['date']}")
    print(f"  URL:   {weekly['url']}")

    # Step 2: Fetch article content
    print("\n[Step 2] Fetching article content...")
    text = fetch_article_content(weekly["url"])
    if text is None:
        print("  FAIL: Could not fetch article content.")
        return False

    blurb = weekly.get("blurb", "")
    if blurb:
        print(f"  API blurb ({len(blurb)} chars): {blurb[:200]}...")
        text = text + "\n" + blurb

    print(f"  OK: Extracted {len(text)} characters of text")
    # Show first 500 chars as preview
    preview = text[:500].replace("\n", " ")
    print(f"  Preview: {preview}...")

    # Step 3: Parse bonuses
    print("\n[Step 3] Parsing bonuses...")
    bonuses = parse_bonuses(text)
    if bonuses:
        for b in bonuses:
            print(f"  - {b}")
    else:
        print("  No bonuses found (article may not contain bonus info)")

    # Step 4: Parse discounts
    print("\n[Step 4] Parsing discounts...")
    discounts = parse_discounts(text)
    if discounts:
        for d in discounts:
            print(f"  - {d['discount']} off {d['item']} [{d['category']}]")
    else:
        print("  No discounts found (article may not contain discount info)")

    # Step 5: Parse podium vehicle
    print("\n[Step 5] Parsing podium vehicle...")
    podium = parse_podium_vehicle(text)
    if podium:
        print(f"  Podium Vehicle: {podium}")
    else:
        print("  No podium vehicle found")

    # Step 6: Full combined parse
    print("\n[Step 6] Running parse_full_article()...")
    result = parse_full_article(weekly["url"])
    if result:
        print(f"  Bonuses:  {len(result['bonuses'])}")
        print(f"  Discounts: {len(result['discounts'])}")
        print(f"  Podium:   {result['podium_vehicle'] or 'none'}")
        print(f"  Raw text: {len(result['raw_text'])} chars")
    else:
        print("  FAIL: parse_full_article returned None")

    print("\n" + "=" * 60)
    print("  Parser test complete.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_parser()
