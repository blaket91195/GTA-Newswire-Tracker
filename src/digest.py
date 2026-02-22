"""Format and display the weekly GTA Online digest."""


def format_digest(article_info, wishlist_matches=None):
    """Format the parsed article data into a readable digest.

    Args:
        article_info: Dict with 'bonuses', 'discounts', 'podium_vehicle' keys.
            - bonuses: list of strings (e.g. "2X on Cayo Perico Heist")
            - discounts: list of dicts {"item": ..., "discount": ..., "category": ...}
            - podium_vehicle: str or None
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
    lines.append("PODIUM VEHICLE:")
    if article_info.get("podium_vehicle"):
        lines.append(f"  >> {article_info['podium_vehicle']}")
    else:
        lines.append("  Not found.")

    lines.append("")
    lines.append("PRIZE RIDE:")
    if article_info.get("prize_ride"):
        lines.append(f"  >> {article_info['prize_ride']}")
    else:
        lines.append("  Not found.")

    # Bonuses
    lines.append("")
    lines.append("BONUSES & EVENTS:")
    bonuses = article_info.get("bonuses", [])
    if bonuses:
        for bonus in bonuses:
            lines.append(f"  - {bonus}")
    else:
        lines.append("  No bonuses found.")

    # Discounts
    lines.append("")
    lines.append("DISCOUNTS:")
    discounts = article_info.get("discounts", [])
    if discounts:
        for disc in discounts:
            if isinstance(disc, dict):
                lines.append(f"  - {disc['discount']} off {disc['item']} [{disc.get('category', '')}]")
            else:
                lines.append(f"  - {disc}")
    else:
        lines.append("  No discounts found.")

    # Wishlist alerts
    if wishlist_matches:
        lines.append("")
        lines.append("*" * 50)
        lines.append("  WISHLIST ALERT! Items on sale:")
        for item in wishlist_matches:
            if isinstance(item, dict):
                stars = "*" * item.get("priority", 3)
                discount = item.get("discount", "")
                disc_str = f" - {discount} off" if discount else ""
                lines.append(f"  >>> [{stars:>5s}] {item['name']}{disc_str} <<<")
            else:
                lines.append(f"  >>> {item} <<<")
        lines.append("*" * 50)

    lines.append("")
    lines.append("=" * 50)
    lines.append("")

    return "\n".join(lines)


def print_digest(article_info, wishlist_matches=None):
    """Print the formatted digest to stdout.

    Args:
        article_info: Dict with 'bonuses', 'discounts', 'podium_vehicle' keys.
        wishlist_matches: Optional list of wishlist items currently on sale.
    """
    print(format_digest(article_info, wishlist_matches))
