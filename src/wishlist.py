"""Wishlist management for tracking desired GTA Online items."""

import json
import os

import config

VALID_CATEGORIES = ("vehicles", "properties", "weapons", "other")


def load_wishlist():
    """Load the wishlist from the JSON file.

    Returns:
        Dict with category keys mapping to lists of item names.
    """
    if not os.path.exists(config.WISHLIST_FILE):
        return {cat: [] for cat in VALID_CATEGORIES}

    with open(config.WISHLIST_FILE, "r") as f:
        return json.load(f)


def save_wishlist(wishlist):
    """Save the wishlist to the JSON file.

    Args:
        wishlist: Dict with category keys mapping to lists of item names.
    """
    os.makedirs(os.path.dirname(config.WISHLIST_FILE), exist_ok=True)
    with open(config.WISHLIST_FILE, "w") as f:
        json.dump(wishlist, f, indent=4)


def add_item(name, category="other"):
    """Add an item to the wishlist.

    Args:
        name: Item name to add.
        category: One of 'vehicles', 'properties', 'weapons', 'other'.

    Returns:
        True if added, False if already exists or invalid category.
    """
    if category not in VALID_CATEGORIES:
        print(f"Invalid category '{category}'. Use one of: {VALID_CATEGORIES}")
        return False

    wishlist = load_wishlist()
    if name.lower() in [item.lower() for item in wishlist[category]]:
        print(f"'{name}' is already in your {category} wishlist.")
        return False

    wishlist[category].append(name)
    save_wishlist(wishlist)
    print(f"Added '{name}' to {category} wishlist.")
    return True


def remove_item(name, category="other"):
    """Remove an item from the wishlist.

    Args:
        name: Item name to remove.
        category: One of 'vehicles', 'properties', 'weapons', 'other'.

    Returns:
        True if removed, False if not found or invalid category.
    """
    if category not in VALID_CATEGORIES:
        print(f"Invalid category '{category}'. Use one of: {VALID_CATEGORIES}")
        return False

    wishlist = load_wishlist()
    matches = [item for item in wishlist[category] if item.lower() == name.lower()]

    if not matches:
        print(f"'{name}' not found in your {category} wishlist.")
        return False

    wishlist[category].remove(matches[0])
    save_wishlist(wishlist)
    print(f"Removed '{name}' from {category} wishlist.")
    return True


def list_wishlist():
    """Display all items in the wishlist.

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

    for category, items in wishlist.items():
        if items:
            print(f"\n  {category.upper()}:")
            for item in items:
                print(f"    - {item}")

    print(f"\n  Total items: {total}")
    print(f"{'='*40}\n")
    return wishlist


def check_discounts(discounts):
    """Check if any wishlist items appear in the current discounts.

    Args:
        discounts: List of discount description strings.

    Returns:
        List of matching item names found on sale.
    """
    wishlist = load_wishlist()
    matches = []
    discount_text = " ".join(discounts).lower()

    for category, items in wishlist.items():
        for item in items:
            if item.lower() in discount_text:
                matches.append(item)

    return matches
