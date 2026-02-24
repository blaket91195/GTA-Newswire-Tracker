"""Vehicle/property price database for GTA Online.

Stores base prices, trade prices, and metadata for vehicles, properties,
and heists in data/prices.json.  When a price isn't in the local database,
the wiki_lookup module can fetch it from the GTA Wiki automatically.
"""

import json
import logging
import os
import re

import config

logger = logging.getLogger(__name__)

VALID_CATEGORIES = ("vehicles", "properties", "heists")

# Reuse the manufacturer list from wishlist for normalisation
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


def _normalize(name):
    """Normalize a name for fuzzy comparison.

    Strips manufacturer prefixes, lowercases, removes special chars.
    """
    lower = name.lower().strip()
    for mfr in sorted(_MANUFACTURERS, key=len, reverse=True):
        if lower.startswith(mfr + " "):
            lower = lower[len(mfr):].strip()
            break
    lower = re.sub(r"[^a-z0-9\s]", "", lower)
    return re.sub(r"\s+", " ", lower).strip()


def _default_db():
    """Return an empty price database."""
    return {cat: {} for cat in VALID_CATEGORIES}


def load_prices():
    """Load the price database from data/prices.json.

    Returns:
        Dict with 'vehicles', 'properties', 'heists' keys.
    """
    if not os.path.exists(config.PRICES_FILE):
        return _default_db()

    try:
        with open(config.PRICES_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_db()

    # Ensure all categories exist
    db = _default_db()
    for cat in VALID_CATEGORIES:
        db[cat] = data.get(cat, {})
    return db


def _save_prices(db):
    """Save the price database to data/prices.json."""
    os.makedirs(os.path.dirname(config.PRICES_FILE), exist_ok=True)
    with open(config.PRICES_FILE, "w") as f:
        json.dump(db, f, indent=2)


def get_item_price(item_name):
    """Fuzzy search for an item across vehicles and properties.

    Args:
        item_name: Item name to look up (fuzzy matched).

    Returns:
        Dict with the item's price info and its canonical name,
        or None if not found.
    """
    db = load_prices()
    query = _normalize(item_name)

    # Pass 1: exact normalised match
    for cat in VALID_CATEGORIES:
        for name, info in db[cat].items():
            if _normalize(name) == query:
                return {"name": name, "category_key": cat, **info}

    # Pass 2: partial match (query in name or name in query)
    for cat in VALID_CATEGORIES:
        for name, info in db[cat].items():
            norm = _normalize(name)
            if query in norm or norm in query:
                return {"name": name, "category_key": cat, **info}

    return None


def get_or_fetch_price(item_name):
    """Look up an item's price, falling back to GTA Wiki if not in local DB.

    1. Checks the local prices.json database (fuzzy match).
    2. If not found, queries the GTA Wiki MediaWiki API for the price.
    3. If the wiki returns a price, caches it into prices.json for future use.

    Args:
        item_name: Item name to look up.

    Returns:
        Dict with price info and canonical name, or None if not found
        anywhere.  Wiki-sourced results include ``"source": "gta_wiki"``.
    """
    # Try local database first
    local = get_item_price(item_name)
    if local is not None:
        return local

    # Fall back to wiki lookup
    try:
        from src.wiki_lookup import lookup_price
    except ImportError:
        logger.debug("wiki_lookup module not available")
        return None

    logger.info("Price not in local DB for '%s', trying GTA Wiki...", item_name)
    wiki_result = lookup_price(item_name)
    if wiki_result is None:
        return None

    # Determine category — wiki lookup returns vehicles by default
    vtype = wiki_result.get("type", "vehicle")
    if vtype in ("business", "office", "property", "warehouse",
                 "clubhouse", "facility", "hangar", "mc_business"):
        category = "properties"
    else:
        category = "vehicles"

    # Build the entry and save to local DB
    entry = {
        "base_price": wiki_result["base_price"],
        "category": _cat_label(category),
        "source": "gta_wiki",
    }
    if wiki_result.get("trade_price"):
        entry["trade_price"] = wiki_result["trade_price"]
    if wiki_result.get("type"):
        entry["type"] = wiki_result["type"]
    wiki_title = wiki_result.get("wiki_title", item_name)
    entry["notes"] = f"Price auto-fetched from GTA Wiki ({wiki_title})"

    # Save to local database for future lookups
    db = load_prices()
    db[category][item_name] = entry
    _save_prices(db)
    logger.info(
        "Cached wiki price for '%s': $%s in %s",
        item_name, f"{wiki_result['base_price']:,}", category,
    )

    return {"name": item_name, "category_key": category, **entry}


def add_item_price(category, item_name, base_price, **kwargs):
    """Add a new item to the price database.

    Args:
        category: One of 'vehicles', 'properties', 'heists'.
        item_name: Display name for the item.
        base_price: Base price in GTA$.
        **kwargs: Optional fields — trade_price, max_price, type,
                  notes, avg_payout, avg_time_minutes, requirements.

    Returns:
        True if added, False if category invalid or item already exists.
    """
    if category not in VALID_CATEGORIES:
        print(f"Invalid category '{category}'. Use one of: {', '.join(VALID_CATEGORIES)}")
        return False

    db = load_prices()

    if item_name in db[category]:
        print(f"'{item_name}' already exists in {category}.")
        return False

    entry = {"base_price": int(base_price), "category": _cat_label(category)}

    # Allowed optional fields per category
    allowed = {
        "vehicles": ["trade_price", "type", "notes"],
        "properties": ["max_price", "type", "notes"],
        "heists": ["avg_payout", "avg_time_minutes", "requirements", "notes"],
    }

    for key in allowed.get(category, []):
        if key in kwargs and kwargs[key] is not None:
            val = kwargs[key]
            if key in ("trade_price", "max_price", "avg_payout", "avg_time_minutes"):
                val = int(val)
            entry[key] = val

    db[category][item_name] = entry
    _save_prices(db)
    print(f"Added '{item_name}' to {category} (${base_price:,}).")
    return True


def update_item_price(item_name, **kwargs):
    """Update an existing item's price info.

    Finds the item via fuzzy search, then merges the provided kwargs
    into its existing data.

    Args:
        item_name: Name of the item to update (fuzzy matched).
        **kwargs: Fields to update — base_price, trade_price, max_price,
                  type, notes, avg_payout, avg_time_minutes, requirements.

    Returns:
        True if updated, False if not found.
    """
    db = load_prices()
    query = _normalize(item_name)

    for cat in VALID_CATEGORIES:
        for name, info in db[cat].items():
            norm = _normalize(name)
            if query == norm or query in norm or norm in query:
                for key, val in kwargs.items():
                    if val is not None:
                        if key in ("base_price", "trade_price", "max_price",
                                   "avg_payout", "avg_time_minutes"):
                            val = int(val)
                        info[key] = val
                _save_prices(db)
                print(f"Updated '{name}' in {cat}.")
                return True

    print(f"'{item_name}' not found in price database.")
    return False


def search_items(query):
    """Fuzzy search across all items in the price database.

    Args:
        query: Search string (fuzzy matched against item names).

    Returns:
        List of dicts with 'name', 'category_key', and all price fields.
    """
    db = load_prices()
    q = _normalize(query)
    results = []

    for cat in VALID_CATEGORIES:
        for name, info in db[cat].items():
            norm = _normalize(name)
            if q in norm or norm in q:
                results.append({"name": name, "category_key": cat, **info})

    return results


def format_price_info(item):
    """Format a price info dict for terminal display.

    Args:
        item: Dict from get_item_price() or search_items().

    Returns:
        Formatted multi-line string.
    """
    lines = [f"  {item['name']}"]

    if "base_price" in item:
        lines.append(f"    Base Price:  ${item['base_price']:,}")
    if "trade_price" in item:
        lines.append(f"    Trade Price: ${item['trade_price']:,}")
    if "max_price" in item:
        lines.append(f"    Max Price:   ${item['max_price']:,}")
    if "avg_payout" in item:
        lines.append(f"    Avg Payout:  ${item['avg_payout']:,}")
    if "avg_time_minutes" in item:
        lines.append(f"    Avg Time:    {item['avg_time_minutes']} min")
    if "type" in item:
        lines.append(f"    Type:        {item['type']}")
    if "requirements" in item:
        lines.append(f"    Requires:    {', '.join(item['requirements'])}")
    if "notes" in item:
        lines.append(f"    Notes:       {item['notes']}")

    return "\n".join(lines)


def _cat_label(category_key):
    """Map a category key to a display label."""
    return {"vehicles": "vehicle", "properties": "property", "heists": "heist"}.get(
        category_key, category_key
    )
