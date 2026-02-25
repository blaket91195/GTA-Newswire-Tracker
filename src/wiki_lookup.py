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
# Manufacturer prefixes (stripped before wiki search)
# ---------------------------------------------------------------------------

# GTA vehicle manufacturers — Reddit/Newswire posts often include these
# but wiki page titles typically omit them (e.g. "Zentorno" not
# "Pegassi Zentorno").
_MANUFACTURERS = [
    "albany", "annis", "benefactor", "bf", "bollokan", "bravado",
    "brute", "buckingham", "canis", "chariot", "cheval", "classique",
    "coil", "declasse", "dewbauchee", "dinka", "dundreary", "emperor",
    "enus", "fathom", "gallivanter", "grotti", "hvy", "hijak",
    "imponte", "invetero", "jacksheepe", "jobuilt", "karin",
    "lampadati", "maibatsu", "mammoth", "maxwell", "nagasaki",
    "obey", "ocelot", "overflod", "pegassi", "pfister", "principe",
    "progen", "rune", "schyster", "shitzu", "stanley", "truffade",
    "ubermacht", "\u00fcbermacht", "vapid", "vulcar", "vysser",
    "weeny", "western", "western company", "willard", "zirconium",
]


def _strip_manufacturer(name):
    """Strip a manufacturer prefix from a vehicle name.

    "Pegassi Zentorno" → "Zentorno"
    "Mammoth Avenger"  → "Avenger"
    "Oppressor Mk II"  → "Oppressor Mk II"  (no prefix)
    """
    lower = name.lower().strip()
    for mfr in sorted(_MANUFACTURERS, key=len, reverse=True):
        if lower.startswith(mfr + " "):
            return name[len(mfr):].strip()
    return name.strip()


# ---------------------------------------------------------------------------
# Price extraction patterns
# ---------------------------------------------------------------------------

# Matches prices like "$1,245,000" or "$3,890,250"
_RE_PRICE = re.compile(r"\$[\d,]+")

# Matches "GTA$1,245,000" or "GTA$ 1,245,000"
_RE_GTA_PRICE = re.compile(r"GTA\$\s?[\d,]+")

# Wiki templates that embed prices: {{GTAO|1245000}}, {{GTA Online|$1,245,000}},
# {{Money|1245000}}, {{Price|725000}}, {{formatnum:1245000}}
_RE_TEMPLATE_PRICE = re.compile(
    r"\{\{\s*(?:GTAO|GTA Online|Money|Price|formatnum)\s*[:|]\s*\$?\s*([\d,]+)",
    re.IGNORECASE,
)

# Wikitext infobox price fields — capture the field name and value.
# Handles: |price1 = ..., |price_online = ..., |trade_price = ..., |sellprice = ...
# Uses newline as delimiter (not |) since values can contain | inside templates.
_RE_INFOBOX_PRICE = re.compile(
    r"\|\s*(price\d?|price[-_ ]?online|trade[-_ ]?price|sell[-_ ]?price|cost)\s*=\s*(.+)",
    re.IGNORECASE,
)

# Property infobox sometimes uses different field names
_RE_INFOBOX_COST = re.compile(
    r"\|\s*(base[-_ ]?price|min[-_ ]?price|max[-_ ]?price|cost)\s*=\s*(.+)",
    re.IGNORECASE,
)


def _parse_dollar_amount(text):
    """Extract the first dollar amount from text, returning an int.

    Handles "$1,245,000", "GTA$3,890,250", "GTA$ 1,245,000",
    "{{GTAO|1245000}}", "{{Money|1,245,000}}", "{{formatnum:1245000}}".
    Returns None if no amount found.
    """
    # Try wiki template formats first (before stripping templates!)
    # {{GTAO|1245000}}, {{Money|1,245,000}}, {{Price|725000}}, {{formatnum:1245000}}
    m = _RE_TEMPLATE_PRICE.search(text)
    if m:
        digits = m.group(1).replace(",", "")
        if digits.isdigit() and int(digits) >= 1000:
            return int(digits)

    # Try GTA$ format
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


def _try_exact_title(title):
    """Try an exact title lookup.  Returns the page title or None."""
    data = _wiki_request({
        "action": "query",
        "titles": title,
        "prop": "info",
    })
    if data:
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid != "-1" and "missing" not in page:
                return page["title"]
    return None


def _search_wiki_page(item_name):
    """Search for a wiki page matching the item name.

    Tries several title variants, then falls back to search.
    Returns the page title or None.
    """
    title_guess = item_name.strip()

    # Build a list of candidate titles to try (in priority order)
    candidates = [title_guess]

    # Strip common article prefixes ("The Oppressor" → "Oppressor")
    stripped_article = re.sub(
        r"^(?:the|a|an)\s+", "", title_guess, flags=re.IGNORECASE
    ).strip()
    if stripped_article != title_guess:
        candidates.append(stripped_article)

    # Strip manufacturer prefix ("Pegassi Zentorno" → "Zentorno")
    stripped_mfr = _strip_manufacturer(title_guess)
    if stripped_mfr != title_guess:
        candidates.append(stripped_mfr)

    # Both: strip article prefix then manufacturer
    stripped_both = _strip_manufacturer(stripped_article)
    if stripped_both not in candidates:
        candidates.append(stripped_both)

    # Try each candidate as an exact title
    for candidate in candidates:
        result = _try_exact_title(candidate)
        if result:
            return result

    # Try with common GTA Wiki disambiguation suffixes.
    # Only apply to the manufacturer-stripped candidate to reduce API calls.
    best_candidate = stripped_mfr if stripped_mfr != title_guess else title_guess
    for suffix in [
        "(HD Universe)",   # most common for vehicles in multiple game eras
        "(HD)",            # shorter variant
        "(GTA Online)",    # online-specific pages
    ]:
        result = _try_exact_title(f"{best_candidate} {suffix}")
        if result:
            return result

    # Fall back to search API — use the shortest (most specific) candidate
    search_name = min(candidates, key=len)
    data = _wiki_request({
        "action": "query",
        "list": "search",
        "srsearch": f"{search_name} GTA Online",
        "srlimit": 5,
    })
    if not data:
        return None

    results = data.get("query", {}).get("search", [])
    if not results:
        return None

    # Build normalised names for matching (lowercase, no manufacturer)
    match_names = set()
    for c in candidates:
        match_names.add(c.lower())

    # Prefer results whose title closely matches any candidate name
    for result in results:
        title_lower = result["title"].lower()
        for mn in match_names:
            if mn in title_lower or title_lower in mn:
                return result["title"]

    # Return the top result as a fallback
    return results[0]["title"]


def _fetch_page_wikitext(page_title):
    """Fetch the raw wikitext for a wiki page.

    Follows redirects so that e.g. "Jugular" resolves to
    "Jugular (HD Universe)" transparently.

    Returns wikitext string or None.
    """
    data = _wiki_request({
        "action": "query",
        "titles": page_title,
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "redirects": "1",           # follow redirects
    })
    if not data:
        return None

    pages = data.get("query", {}).get("pages", {})
    for pid, page in pages.items():
        if pid == "-1" or "missing" in page:
            continue
        revisions = page.get("revisions", [])
        if not revisions:
            continue

        rev = revisions[0]

        # New MediaWiki format (1.32+): slots → main → content
        slots = rev.get("slots", {})
        main = slots.get("main", {})
        content = main.get("*") or main.get("content")
        if content:
            return content

        # Old MediaWiki / Fandom format: content directly on revision
        content = rev.get("*") or rev.get("content")
        if content:
            return content

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

    # Strategy 0: Scan for wiki price templates anywhere in the text.
    # These are authoritative and unambiguous.
    for m in _RE_TEMPLATE_PRICE.finditer(wikitext):
        digits = m.group(1).replace(",", "")
        if digits.isdigit():
            val = int(digits)
            if 1000 <= val <= 100000000:
                # Check context — is this near a "trade" keyword?
                start = max(0, m.start() - 60)
                context = wikitext[start:m.start()].lower()
                if "trade" in context:
                    if trade_price is None or val < trade_price:
                        trade_price = val
                else:
                    if base_price is None or val > base_price:
                        base_price = val

    # Strategy 1: Parse infobox price fields
    for match in _RE_INFOBOX_PRICE.finditer(wikitext):
        field_name = match.group(1).lower().replace("-", "_").replace(" ", "_")
        field_value = match.group(2)
        amount = _parse_dollar_amount(field_value)
        if amount is None:
            continue

        if "trade" in field_name:
            if trade_price is None:
                trade_price = amount
        elif "sell" in field_name:
            pass  # sell price is not what we want
        elif base_price is None or amount > base_price:
            base_price = amount

    # Also check cost-style fields
    for match in _RE_INFOBOX_COST.finditer(wikitext):
        field_name = match.group(1).lower().replace("-", "_").replace(" ", "_")
        field_value = match.group(2)
        amount = _parse_dollar_amount(field_value)
        if amount and base_price is None:
            base_price = amount

    # Pre-clean wikitext for Strategies 2 and 3:
    # [[$]] → $, {{GTA$}} → $, {{GTAO$}} → $, '''bold''' → content
    cleaned_wt = re.sub(r"\[\[\$\]\]", "$", wikitext)
    cleaned_wt = re.sub(r"\{\{\s*(?:GTA|GTAO)?\$\s*\}\}", "$", cleaned_wt)
    cleaned_wt = re.sub(r"'{2,3}", "", cleaned_wt)

    # Strategy 2: If no infobox prices, look for prices in body text.
    # GTA Wiki often puts the price in prose like:
    #   "can be purchased from [[Legendary Motorsport]] for $1,225,000"
    #   "can be purchased from [[Store]] for [[$]]1,225,000"
    #   "costs $797,000 from [[Southern SA Super Autos]]"
    # Allow up to 120 chars between the verb and the price to accommodate
    # store names in wikilinks.
    if base_price is None:
        price_context = re.findall(
            r"(?:available|purchase[d]?|bought|costs?|priced?|buy|sold)\b"
            r".{0,120}?"
            r"\$([\d,]+)",
            cleaned_wt, re.IGNORECASE,
        )
        for price_str in price_context:
            digits = price_str.replace(",", "")
            if digits.isdigit():
                val = int(digits)
                if 10000 <= val <= 100000000:
                    base_price = val
                    break

    # Strategy 3: Last resort — find ANY dollar amount on the page that
    # looks like a GTA Online vehicle price ($10K–$100M).  Take the highest
    # value, which is typically the base purchase price.
    if base_price is None:
        all_prices = []
        for m in re.finditer(r"\$([\d,]{5,})", cleaned_wt):
            digits = m.group(1).replace(",", "")
            if digits.isdigit():
                val = int(digits)
                if 10000 <= val <= 100000000:
                    all_prices.append(val)
        if all_prices:
            base_price = max(all_prices)

    if base_price is None:
        return None

    # Sanity check: trade price should be less than base price
    if trade_price and base_price and trade_price >= base_price:
        trade_price = None

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
