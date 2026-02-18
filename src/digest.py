"""Format and display the weekly GTA Online digest."""


def format_digest(article_info, wishlist_matches=None):
    """Format the parsed article data into a readable digest.

    Args:
        article_info: Dict with 'discounts', 'events', 'podium_vehicle' keys.
        wishlist_matches: Optional list of wishlist items currently on sale.

    Returns:
        Formatted digest string.
    """
    lines = []
    lines.append("")
    lines.append("=" * 50)
    lines.append("   GTA ONLINE - WEEKLY UPDATE DIGEST")
    lines.append("=" * 50)

    # Podium / Prize vehicle
    lines.append("")
    lines.append("PODIUM / PRIZE VEHICLE:")
    if article_info.get("podium_vehicle"):
        lines.append(f"  >> {article_info['podium_vehicle']}")
    else:
        lines.append("  No podium vehicle info found.")

    # Events & Bonuses
    lines.append("")
    lines.append("EVENTS & BONUSES:")
    if article_info.get("events"):
        for event in article_info["events"]:
            lines.append(f"  - {event}")
    else:
        lines.append("  No events found.")

    # Discounts
    lines.append("")
    lines.append("DISCOUNTS:")
    if article_info.get("discounts"):
        for discount in article_info["discounts"]:
            lines.append(f"  - {discount}")
    else:
        lines.append("  No discounts found.")

    # Wishlist alerts
    if wishlist_matches:
        lines.append("")
        lines.append("*" * 50)
        lines.append("  WISHLIST ALERT! Items on sale:")
        for item in wishlist_matches:
            lines.append(f"  >>> {item} <<<")
        lines.append("*" * 50)

    lines.append("")
    lines.append("=" * 50)
    lines.append("")

    return "\n".join(lines)


def print_digest(article_info, wishlist_matches=None):
    """Print the formatted digest to stdout.

    Args:
        article_info: Dict with 'discounts', 'events', 'podium_vehicle' keys.
        wishlist_matches: Optional list of wishlist items currently on sale.
    """
    print(format_digest(article_info, wishlist_matches))
