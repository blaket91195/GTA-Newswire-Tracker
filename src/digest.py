"""Format and display the weekly GTA Online digest."""

import os
import re
from datetime import datetime

from src.prices import load_prices
from src.roi_calculator import (
    calculate_discount_savings,
    calculate_business_roi,
    calculate_heist_roi,
    INCOME_RATES,
)


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
        prices_db = _load_prices_safe()
        sorted_discounts = sorted(
            discounts,
            key=lambda d: _discount_sort_key(d, norm_matches),
        )
        # Build set of recommended item names (HIGH-priority wishlist matches)
        rec_names = set()
        for wm in norm_matches:
            if wm["priority"] >= 4:
                rec_names.add(wm["discount_item"].lower())

        for disc in sorted_discounts:
            if isinstance(disc, dict):
                item_name = disc["item"]
                cat = disc.get("category", "")
                is_rec = item_name.lower() in rec_names
                rec_tag = " \u2b50 RECOMMENDED" if is_rec else ""

                lines.append(
                    f"  - {disc['discount']} off {item_name}"
                    f" [{cat}]{rec_tag}"
                )

                # Add ROI annotation if price data is available
                roi_line = _build_roi_annotation(item_name, disc.get("discount", ""), prices_db)
                if roi_line:
                    lines.append(f"    {roi_line}")
            else:
                lines.append(f"  - {disc}")
    else:
        lines.append("  No discounts found.")

    lines.append("")
    lines.append("=" * 50)
    lines.append("")

    return "\n".join(lines)


def _load_prices_safe():
    """Load price database, returning empty dict on failure."""
    try:
        return load_prices()
    except Exception:
        return {"vehicles": {}, "properties": {}, "heists": {}}


def _build_roi_annotation(item_name, discount_str, prices_db):
    """Build a one-line ROI annotation string for a discount item.

    Returns a string like:
        ``"Save: $660,000 | ROI: 447% | Break-even: 1 heist"``
    or None if the item isn't in the price database.
    """
    if not prices_db:
        return None

    pct_match = re.search(r"(\d+)", str(discount_str))
    if not pct_match:
        return None
    pct = int(pct_match.group(1))

    savings = calculate_discount_savings(item_name, pct, prices_db)
    if not savings:
        return None

    parts = [f"Save: ${savings['savings_vs_base']:,}"]

    # Check heist ROI
    heist = _find_heist_for_digest(savings["item"], prices_db)
    biz = calculate_business_roi(savings["item"], prices_db)

    if heist:
        sale_price = savings["best_price"]
        payout = heist["avg_payout_per_run"]
        break_even = round(sale_price / payout, 1) if payout else 0
        parts.append(f"ROI: {heist['roi_30_days']}")
        be_label = f"{break_even} heist" if break_even <= 1.5 else f"{break_even} heists"
        parts.append(f"Break-even: {be_label}")
    elif biz:
        parts.append(f"ROI: {biz['roi_30_days']}")
        income_type = biz["income_type"].capitalize()
        parts.append(f"{income_type} income")
    else:
        # Utility item — show what it's best for from notes
        item_info = _find_item_notes(savings["item"], prices_db)
        if item_info:
            parts.append(f"Best for: {item_info}")

    return " | ".join(parts)


def _find_heist_for_digest(item_name, prices_db):
    """Check if item is a heist requirement and return that heist's ROI."""
    norm = item_name.lower().strip()
    for hname, hinfo in prices_db.get("heists", {}).items():
        for req in hinfo.get("requirements", []):
            if req.lower() in norm or norm in req.lower():
                return calculate_heist_roi(hname, prices_db=prices_db)
    return None


def _find_item_notes(item_name, prices_db):
    """Look up item notes from the price database."""
    norm = item_name.lower().strip()
    for cat in ("vehicles", "properties"):
        for name, info in prices_db.get(cat, {}).items():
            if name.lower() == norm or norm in name.lower():
                notes = info.get("notes", "")
                # Return a short version of notes
                if notes and len(notes) > 40:
                    return notes[:40].rsplit(" ", 1)[0] + "..."
                return notes
    return None


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
