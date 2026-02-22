"""Format and display the weekly GTA Online digest."""

import os
import re
from datetime import datetime


def _extract_parsed(article_data):
    """Normalise article_data to the flat parsed-content dict.

    Accepts both the new nested structure::

        {"article_metadata": {...}, "parsed_content": {...}}

    and the legacy flat structure::

        {"discounts": [...], "bonuses": [...], "podium_vehicle": "..."}
    """
    if "parsed_content" in article_data:
        return article_data["parsed_content"]
    return article_data


def _extract_metadata(article_data):
    """Pull optional article metadata (title, date, url)."""
    return article_data.get("article_metadata", {})


def _normalise_match(m):
    """Normalise a wishlist-match dict to a consistent shape.

    Accepts both::

        # new spec
        {"wishlist_item": "X", "matched_discount": {"item": "Y", "discount": "40%"}, "priority": 5}

        # legacy from match_discounts()
        {"name": "X", "discount_item": "Y", "discount": "40%", "priority": 5}
    """
    if "wishlist_item" in m:
        md = m.get("matched_discount", {})
        return {
            "wishlist_item": m["wishlist_item"],
            "discount_item": md.get("item", ""),
            "discount": md.get("discount", ""),
            "priority": m.get("priority", 3),
        }
    return {
        "wishlist_item": m.get("name", ""),
        "discount_item": m.get("discount_item", ""),
        "discount": m.get("discount", ""),
        "priority": m.get("priority", 3),
    }


def _discount_sort_key(disc, matched_items):
    """Sort key: wishlist matches first (by priority desc), then % desc."""
    item_lower = disc["item"].lower() if isinstance(disc, dict) else ""

    # Check if this discount is a wishlist match
    priority = 0
    for mi in matched_items:
        if mi["discount_item"].lower() == item_lower:
            priority = mi["priority"]
            break

    # Extract numeric percentage for secondary sort
    pct = 0
    raw = disc.get("discount", "") if isinstance(disc, dict) else ""
    m = re.search(r"(\d+)", str(raw))
    if m:
        pct = int(m.group(1))

    # Negate so higher values sort first
    return (-priority, -pct)


def format_digest(article_data, wishlist_matches=None):
    """Format the parsed article data into a readable terminal digest.

    Args:
        article_data: Dict — either the new nested structure with
            ``article_metadata`` and ``parsed_content`` keys, or the
            legacy flat dict with ``discounts``, ``bonuses``, etc.
        wishlist_matches: Optional list of wishlist match dicts (new or
            legacy format).  See ``_normalise_match`` for accepted shapes.

    Returns:
        Formatted digest string.
    """
    parsed = _extract_parsed(article_data)
    meta = _extract_metadata(article_data)

    lines = []
    lines.append("")
    lines.append("=" * 50)
    lines.append("   GTA ONLINE - WEEKLY UPDATE DIGEST")
    lines.append("=" * 50)

    # Article metadata (if present)
    if meta.get("title"):
        lines.append(f"  {meta['title']}")
    if meta.get("date"):
        lines.append(f"  Date: {meta['date']}")
    if meta.get("url"):
        lines.append(f"  URL: {meta['url']}")

    # Podium / Prize vehicle
    lines.append("")
    lines.append("PODIUM / PRIZE VEHICLE:")
    podium = parsed.get("podium_vehicle")
    prize = parsed.get("prize_ride")
    if podium:
        lines.append(f"  Podium: {podium}")
    if prize:
        lines.append(f"  Prize Ride: {prize}")
    if not podium and not prize:
        lines.append("  No podium vehicle info found.")

    # Bonuses
    lines.append("")
    lines.append("BONUSES & EVENTS:")
    bonuses = parsed.get("bonuses", [])
    if bonuses:
        for bonus in bonuses:
            lines.append(f"  - {bonus}")
    else:
        lines.append("  No bonuses found.")

    # Normalise wishlist matches
    norm_matches = []
    if wishlist_matches:
        for m in wishlist_matches:
            if isinstance(m, dict):
                norm_matches.append(_normalise_match(m))
            else:
                # Plain string (legacy)
                norm_matches.append({
                    "wishlist_item": str(m),
                    "discount_item": str(m),
                    "discount": "",
                    "priority": 3,
                })

    # Wishlist matches (shown BEFORE discounts)
    if norm_matches:
        lines.append("")
        lines.append("\U0001f3af WISHLIST MATCHES:")
        for wm in sorted(norm_matches, key=lambda x: -x["priority"]):
            stars = "\u2b50" * wm["priority"]
            disc_str = f"{wm['discount']} off " if wm["discount"] else ""
            display_name = wm["discount_item"] or wm["wishlist_item"]
            lines.append(f"  {stars} {disc_str}{display_name}")

    # Discounts — sorted: wishlist matches first (by priority), then by %
    lines.append("")
    lines.append("DISCOUNTS:")
    discounts = parsed.get("discounts", [])
    if discounts:
        sorted_discounts = sorted(
            discounts,
            key=lambda d: _discount_sort_key(d, norm_matches),
        )
        for disc in sorted_discounts:
            if isinstance(disc, dict):
                lines.append(
                    f"  - {disc['discount']} off {disc['item']}"
                    f" [{disc.get('category', '')}]"
                )
            else:
                lines.append(f"  - {disc}")
    else:
        lines.append("  No discounts found.")

    lines.append("")
    lines.append("=" * 50)
    lines.append("")

    return "\n".join(lines)


def save_digest(digest_text, filename=None):
    """Save digest text to a file with a timestamp header.

    Args:
        digest_text: The formatted digest string.
        filename: Optional path.  Defaults to ``data/digest_YYYY-MM-DD.txt``.

    Returns:
        The path the digest was saved to.
    """
    if filename is None:
        today = datetime.now().strftime("%Y-%m-%d")
        filename = os.path.join("data", f"digest_{today}.txt")

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, "w") as f:
        f.write(f"Generated: {timestamp}\n")
        f.write(digest_text)

    return filename


def print_digest(article_data, wishlist_matches=None):
    """Print the formatted digest to stdout.

    Args:
        article_data: Dict with article/parsed content (nested or flat).
        wishlist_matches: Optional list of wishlist match dicts.
    """
    print(format_digest(article_data, wishlist_matches))
