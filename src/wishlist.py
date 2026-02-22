"""Wishlist management for tracking desired GTA Online items.

JSON structure in data/wishlist.json:
{
  "vehicles": [{"name": "Oppressor Mk II", "priority": 5}],
  "properties": [{"name": "Nightclub", "priority": 3}],
  "weapons": [],
  "other": []
}
"""

import json
import os
import re
import shutil

import config

VALID_CATEGORIES = ("vehicles", "properties", "weapons", "other")

# Known GTA vehicle manufacturers, stripped during fuzzy matching
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


def _default_wishlist():
    """Return an empty wishlist structure."""
    return {cat: [] for cat in VALID_CATEGORIES}


def normalize_item_name(name):
    """Normalize an item name for fuzzy comparison.

    Strips manufacturer prefixes, lowercases, and removes special chars.
    """
    lower = name.lower().strip()

    # Strip known manufacturer prefix
    for mfr in sorted(_MANUFACTURERS, key=len, reverse=True):
        if lower.startswith(mfr + " "):
            lower = lower[len(mfr):].strip()
            break

    # Remove special characters (keep alphanumeric and spaces)
    lower = re.sub(r"[^a-z0-9\s]", "", lower)
    # Collapse whitespace
    lower = re.sub(r"\s+", " ", lower).strip()
    return lower


def load_wishlist():
    """Load the wishlist from data/wishlist.json.

    Creates the default structure if the file is missing or malformed.

    Returns:
        Dict with category keys mapping to lists of {"name", "priority"} dicts.
    """
    if not os.path.exists(config.WISHLIST_FILE):
        return _default_wishlist()

    try:
        with open(config.WISHLIST_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_wishlist()

    # Migrate plain-string items to {"name": ..., "priority": 3}
    wishlist = _default_wishlist()
    for cat in VALID_CATEGORIES:
        raw_items = data.get(cat, [])
        for item in raw_items:
            if isinstance(item, str):
                wishlist[cat].append({"name": item, "priority": 3})
            elif isinstance(item, dict) and "name" in item:
                wishlist[cat].append({
                    "name": item["name"],
                    "priority": item.get("priority", 3),
                })
    return wishlist


def save_wishlist(wishlist):
    """Save the wishlist to data/wishlist.json.

    Creates a timestamped backup of the existing file before overwriting.
    """
    path = config.WISHLIST_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Backup existing file
    if os.path.exists(path):
        backup = path + ".bak"
        shutil.copy2(path, backup)

    with open(path, "w") as f:
        json.dump(wishlist, f, indent=2)


def add_item(category, item_name, priority=3):
    """Add an item to the wishlist.

    Args:
        category: One of 'vehicles', 'properties', 'weapons', 'other'.
        item_name: Item name to add.
        priority: Priority 1-5 (5 = highest). Default 3.

    Returns:
        True if added, False if already exists or invalid category.
    """
    if category not in VALID_CATEGORIES:
        print(f"Invalid category '{category}'. Use one of: {', '.join(VALID_CATEGORIES)}")
        return False

    priority = max(1, min(5, int(priority)))

    wishlist = load_wishlist()
    existing = [item["name"].lower() for item in wishlist[category]]
    if item_name.lower() in existing:
        print(f"'{item_name}' is already in your {category} wishlist.")
        return False

    wishlist[category].append({"name": item_name, "priority": priority})
    save_wishlist(wishlist)
    print(f"Added '{item_name}' to {category} wishlist (priority {priority}).")
    return True


def remove_item(category, item_name):
    """Remove an item from the wishlist.

    Args:
        category: One of 'vehicles', 'properties', 'weapons', 'other'.
        item_name: Item name to remove.

    Returns:
        True if removed, False if not found or invalid category.
    """
    if category not in VALID_CATEGORIES:
        print(f"Invalid category '{category}'. Use one of: {', '.join(VALID_CATEGORIES)}")
        return False

    wishlist = load_wishlist()
    matches = [item for item in wishlist[category]
               if item["name"].lower() == item_name.lower()]

    if not matches:
        print(f"'{item_name}' not found in your {category} wishlist.")
        return False

    wishlist[category].remove(matches[0])
    save_wishlist(wishlist)
    print(f"Removed '{item_name}' from {category} wishlist.")
    return True


def list_wishlist():
    """Pretty print all wishlist items by category with priority.

    Returns:
        The wishlist dict.
    """
    wishlist = load_wishlist()
    total = sum(len(items) for items in wishlist.values())

    if total == 0:
        print("Your wishlist is empty.")
        return wishlist

    print(f"\n{'='*40}")
    print("       GTA Online Wishlist")
    print(f"{'='*40}")

    priority_stars = {1: "*", 2: "**", 3: "***", 4: "****", 5: "*****"}

    for category, items in wishlist.items():
        if items:
            # Sort by priority descending
            sorted_items = sorted(items, key=lambda x: x["priority"], reverse=True)
            print(f"\n  {category.upper()}:")
            for item in sorted_items:
                stars = priority_stars.get(item["priority"], "***")
                print(f"    [{stars:>5s}] {item['name']}")

    print(f"\n  Total items: {total}")
    print(f"{'='*40}\n")
    return wishlist


def match_discounts(wishlist, discounts):
    """Match wishlist items against current discounts using fuzzy matching.

    Uses case-insensitive partial matching: a wishlist item "Oppressor"
    will match a discount on "Pegassi Oppressor Mk II".

    Args:
        wishlist: Wishlist dict from load_wishlist().
        discounts: List of {"item": "...", "discount": "..."} dicts.

    Returns:
        List of {"name", "priority", "category", "discount"} dicts,
        sorted by priority descending.
    """
    matches = []
    seen = set()

    for cat, items in wishlist.items():
        for wish_item in items:
            wish_name = wish_item["name"]
            wish_norm = normalize_item_name(wish_name)

            for disc in discounts:
                disc_item = disc.get("item", "")
                disc_norm = normalize_item_name(disc_item)

                # Partial match: wishlist term appears in discount item or vice versa
                if wish_norm in disc_norm or disc_norm in wish_norm:
                    key = (wish_name.lower(), disc_item.lower())
                    if key not in seen:
                        seen.add(key)
                        matches.append({
                            "name": wish_name,
                            "priority": wish_item["priority"],
                            "category": cat,
                            "discount": disc.get("discount", ""),
                            "discount_item": disc_item,
                        })

    # Sort by priority descending
    matches.sort(key=lambda x: x["priority"], reverse=True)
    return matches


def check_discounts(discount_items):
    """Check if any wishlist items appear in the current discounts.

    Backward-compatible wrapper used by main.py when discount data is
    a simple list of item-name strings (no discount percentage).

    Args:
        discount_items: List of discount item name strings.

    Returns:
        List of matching wishlist item names found on sale.
    """
    wishlist = load_wishlist()
    # Build discount dicts so we can reuse match_discounts
    disc_dicts = [{"item": name, "discount": ""} for name in discount_items]
    results = match_discounts(wishlist, disc_dicts)
    return [m["name"] for m in results]
