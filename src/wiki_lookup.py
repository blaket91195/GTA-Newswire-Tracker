"""Dynamic price lookup from the GTA Wiki (Fandom MediaWiki API).

When the local price database doesn't have an item mentioned in a Newswire
article, this module queries the GTA Wiki to find its price automatically.
Successfully fetched prices are cached into data/prices.json so future
lookups are instant.

Requires network access to gta.fandom.com.
"""

import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GTA Wiki MediaWiki API
# ---------------------------------------------------------------------------

WIKI_API_URL = "https://gta.fandom.com/api.php"

_HEADERS = {
    "User-Agent": "GTA-Newswire-Tracker/1.0 (price lookup)",
    "Accept": "application/json",
}

# Retry settings
MAX_RETRIES = 2
RETRY_BACKOFF_BASE = 2


# ---------------------------------------------------------------------------
# Price extraction patterns
# ---------------------------------------------------------------------------

# Matches prices like "$1,245,000" or "$3,890,250"
_RE_PRICE = re.compile(r"\$[\d,]+")

# Matches "GTA$1,245,000" or "GTA$ 1,245,000"
_RE_GTA_PRICE = re.compile(r"GTA\$\s?[\d,]+")

# Wikitext infobox price fields — capture the field name and value.
# Handles: |price1 = $1,245,000, |price_online = ..., |trade_price = ...
_RE_INFOBOX_PRICE = re.compile(
    r"\|\s*(price\d?|price_online|trade_price|cost)\s*=\s*(.+?)(?:\n|\|)",
    re.IGNORECASE,
)

# Property infobox sometimes uses different field names
_RE_INFOBOX_COST = re.compile(
    r"\|\s*(base_price|min_price|max_price|cost)\s*=\s*(.+?)(?:\n|\|)",
    re.IGNORECASE,
)


def _parse_dollar_amount(text):
    """Extract the first dollar amount from text, returning an int.

    Handles "$1,245,000", "GTA$3,890,250", "GTA$ 1,245,000".
    Returns None if no amount found.
    """
    # Try GTA$ format first
    m = _RE_GTA_PRICE.search(text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group())
        if digits:
            return int(digits)

    # Try plain $ format
    m = _RE_PRICE.search(text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group())
        if digits:
            return int(digits)

    # Try bare number with commas after stripping wikitext markup
    cleaned = re.sub(r"<[^>]+>", "", text)  # strip HTML tags
    cleaned = re.sub(r"\[\[[^\]]*\|([^\]]*)\]\]", r"\1", cleaned)  # [[link|text]]
    cleaned = re.sub(r"\[\[([^\]]*)\]\]", r"\1", cleaned)  # [[link]]
    cleaned = re.sub(r"\{\{[^}]*\}\}", "", cleaned)  # {{templates}}
    m = re.search(r"([\d,]{4,})", cleaned)
    if m:
        digits = m.group(1).replace(",", "")
        if digits.isdigit() and int(digits) >= 1000:
            return int(digits)

    return None


# ---------------------------------------------------------------------------
# Vehicle type detection
# ---------------------------------------------------------------------------

_VEHICLE_TYPE_MAP = {
    "helicopter": "helicopter",
    "chopper": "helicopter",
    "heli": "helicopter",
    "jet": "jet",
    "plane": "jet",
    "aircraft": "aircraft",
    "boat": "boat",
    "motorcycle": "motorcycle",
    "bike": "motorcycle",
    "tank": "tank",
    "submarine": "submarine",
    "truck": "truck",
    "van": "truck",
    "suv": "car",
    "sedan": "car",
    "coupe": "car",
    "sports": "car",
    "super": "car",
    "muscle": "car",
    "compact": "car",
    "off-road": "car",
}


def _guess_vehicle_type(wikitext):
    """Guess the vehicle type from wikitext content."""
    lower = wikitext.lower()
    for keyword, vtype in _VEHICLE_TYPE_MAP.items():
        if keyword in lower:
            return vtype
    return "vehicle"


# ---------------------------------------------------------------------------
# Wiki API helpers
# ---------------------------------------------------------------------------


def _wiki_request(params, retries=MAX_RETRIES):
    """Make a request to the GTA Wiki MediaWiki API with retry.

    Returns parsed JSON or None on failure.
    """
    params.setdefault("format", "json")
    params.setdefault("origin", "*")

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                WIKI_API_URL,
                params=params,
                headers=_HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.warning("Wiki API timeout (attempt %d/%d)", attempt, retries)
        except requests.ConnectionError as exc:
            logger.warning("Wiki API connection error (attempt %d/%d): %s",
                           attempt, retries, exc)
        except requests.HTTPError as exc:
            logger.error("Wiki API HTTP error: %s", exc)
            return None
        except ValueError:
            logger.error("Wiki API returned invalid JSON")
            return None

        if attempt < retries:
            time.sleep(RETRY_BACKOFF_BASE ** attempt)

    return None


def _search_wiki_page(item_name):
    """Search for a wiki page matching the item name.

    Tries exact title first, then falls back to search.
    Returns the page title or None.
    """
    # Normalise: "Oppressor Mk II" → "Oppressor Mk II"
    # Wiki titles use spaces and title case
    title_guess = item_name.strip()

    # Try exact title lookup first
    data = _wiki_request({
        "action": "query",
        "titles": title_guess,
        "prop": "info",
    })
    if data:
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid != "-1" and "missing" not in page:
                return page["title"]

    # Try with common prefixes stripped
    stripped = re.sub(
        r"^(?:the|a|an)\s+", "", title_guess, flags=re.IGNORECASE
    ).strip()
    if stripped != title_guess:
        data = _wiki_request({
            "action": "query",
            "titles": stripped,
            "prop": "info",
        })
        if data:
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid != "-1" and "missing" not in page:
                    return page["title"]

    # Fall back to search API
    data = _wiki_request({
        "action": "query",
        "list": "search",
        "srsearch": f"{item_name} GTA Online",
        "srlimit": 5,
    })
    if not data:
        return None

    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    # Prefer results whose title closely matches the item name
    item_lower = item_name.lower().strip()
    for result in results:
        title_lower = result["title"].lower()
        if item_lower in title_lower or title_lower in item_lower:
            return result["title"]

    # Return the top result as a fallback
    return results[0]["title"]


def _fetch_page_wikitext(page_title):
    """Fetch the raw wikitext for a wiki page.

    Returns wikitext string or None.
    """
    data = _wiki_request({
        "action": "query",
        "titles": page_title,
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
    })
    if not data:
        return None

    pages = data.get("query", {}).get("pages", {})
    for pid, page in pages.items():
        if pid == "-1" or "missing" in page:
            continue
        revisions = page.get("revisions", [])
        if revisions:
            slots = revisions[0].get("slots", {})
            main = slots.get("main", {})
            return main.get("*") or main.get("content")

    return None


# ---------------------------------------------------------------------------
# Price extraction from wikitext
# ---------------------------------------------------------------------------


def _extract_prices_from_wikitext(wikitext):
    """Extract base_price, trade_price, and vehicle type from wikitext.

    Returns a dict with available fields, e.g.:
        {"base_price": 1245000, "trade_price": None, "type": "car"}
    Returns None if no price could be extracted.
    """
    if not wikitext:
        return None

    base_price = None
    trade_price = None

    # Strategy 1: Parse infobox price fields
    for match in _RE_INFOBOX_PRICE.finditer(wikitext):
        field_name = match.group(1).lower()
        field_value = match.group(2)
        amount = _parse_dollar_amount(field_value)
        if amount is None:
            continue

        if "trade" in field_name:
            trade_price = amount
        elif base_price is None or amount > base_price:
            # Take the highest non-trade price (usually the base/online price)
            base_price = amount

    # Also check cost-style fields
    for match in _RE_INFOBOX_COST.finditer(wikitext):
        field_name = match.group(1).lower()
        field_value = match.group(2)
        amount = _parse_dollar_amount(field_value)
        if amount and base_price is None:
            base_price = amount

    # Strategy 2: If no infobox prices, look for prices in body text
    # Common patterns: "available for $X from Warstock", "costs $X"
    if base_price is None:
        price_context = re.findall(
            r"(?:available|purchase|bought|costs?|priced?|buy)\s+"
            r"(?:for|at|from)?\s*\$?([\d,]+)",
            wikitext, re.IGNORECASE,
        )
        for price_str in price_context:
            digits = price_str.replace(",", "")
            if digits.isdigit():
                val = int(digits)
                # Only accept reasonable GTA Online prices ($10K - $100M)
                if 10000 <= val <= 100000000:
                    base_price = val
                    break

    if base_price is None:
        return None

    vtype = _guess_vehicle_type(wikitext)

    result = {"base_price": base_price, "type": vtype}
    if trade_price:
        result["trade_price"] = trade_price
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup_price(item_name):
    """Look up an item's price from the GTA Wiki.

    Searches for the item on gta.fandom.com, fetches its wiki page,
    and extracts price information from the infobox.

    Args:
        item_name: The item name to look up (e.g. "Paragon R").

    Returns:
        Dict with price info: {"base_price": int, "trade_price": int|None,
        "type": str, "source": "gta_wiki"}, or None if not found.
    """
    logger.info("Wiki lookup: searching for '%s'", item_name)

    page_title = _search_wiki_page(item_name)
    if not page_title:
        logger.info("Wiki lookup: no page found for '%s'", item_name)
        return None

    logger.info("Wiki lookup: found page '%s' for '%s'", page_title, item_name)

    wikitext = _fetch_page_wikitext(page_title)
    if not wikitext:
        logger.info("Wiki lookup: could not fetch wikitext for '%s'", page_title)
        return None

    prices = _extract_prices_from_wikitext(wikitext)
    if not prices:
        logger.info("Wiki lookup: no prices found in '%s'", page_title)
        return None

    prices["source"] = "gta_wiki"
    prices["wiki_title"] = page_title
    logger.info(
        "Wiki lookup: '%s' → base=$%s, trade=$%s",
        item_name,
        f"{prices['base_price']:,}",
        f"{prices.get('trade_price', 'N/A'):,}" if prices.get("trade_price") else "N/A",
    )
    return prices
