#!/usr/bin/env python3
"""GTA Newswire Tracker - Entry point.

Track GTA Online weekly updates, discounts, events, and check your wishlist.

Commands:
    check        Fetch latest weekly update and display digest
    check-roi    Enhanced check with ROI analysis
    roi          Calculate ROI for a discounted item
    compare      Compare all discounted items from latest update
    recommend    Get purchase recommendations for a budget
    list         Show recent GTA Online articles
    test         Run scraper integration test
    test-parser  Run parser integration test
    wishlist     Manage wishlist (add/remove/list)
    price        Look up or manage the price database
"""

import argparse
import re
import sys

from src.scraper import fetch_newswire_articles, get_latest_weekly_update, test_scraper
from src.reddit_scraper import fetch_weekly_update as reddit_fetch, test_reddit_scraper
from src.parser import parse_full_article, test_parser
from src.wishlist import (
    add_item, remove_item, list_wishlist,
    load_wishlist, match_discounts,
)
from src.digest import format_digest, print_digest, save_digest
from src.prices import (
    load_prices, get_item_price, add_item_price,
    update_item_price, search_items, format_price_info,
)
from src.roi_calculator import (
    calculate_discount_savings,
    calculate_business_roi,
    calculate_heist_roi,
    compare_investments,
    generate_purchase_recommendation,
    INCOME_RATES,
)
from src.comparison import (
    format_currency,
    generate_comparison_table,
    generate_discount_chart,
)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def cmd_check(args):
    """Fetch the latest weekly update and display the digest.

    Workflow:
        1. get_latest_weekly_update() or reddit fetch
        2. parse_full_article(url, blurb)
        3. load_wishlist()
        4. match_discounts(wishlist, parsed["discounts"])
        5. format_digest(article_data, wishlist_matches)
        6. Display to terminal (and optionally save)
    """
    source = getattr(args, "source", "reddit")
    do_save = getattr(args, "save", False)

    article_data = None

    # --- Reddit source ---
    if source in ("reddit", "auto"):
        print("Fetching latest weekly update from r/gtaonline...")
        result = reddit_fetch()

        if result and (result["discounts"] or result["podium_vehicle"]):
            print(f"Source: Reddit — {result['title']}")
            print(f"URL: {result['source_url']}")
            article_data = result

        elif source == "reddit":
            print("Reddit source had no detailed data, trying Rockstar API...")

    # --- Rockstar Newswire fallback ---
    if article_data is None:
        print("Fetching latest GTA Online newswire...")
        weekly = get_latest_weekly_update()
        if weekly is None:
            print("Could not find a recent weekly update article.")
            print("Try running 'list' to see all recent articles.")
            sys.exit(1)

        print(f"Latest weekly update: {weekly['title']}")
        print(f"Date: {weekly['date']}")
        print(f"URL: {weekly['url']}")

        print("Fetching article content...")
        parsed = parse_full_article(weekly["url"], blurb=weekly.get("blurb", ""))

        if parsed is None:
            print("Could not fetch article content.")
            article_data = {"discounts": [], "bonuses": [], "podium_vehicle": None}
        else:
            article_data = parsed

    # --- Wishlist matching ---
    wishlist = load_wishlist()
    wishlist_matches = match_discounts(wishlist, article_data.get("discounts", []))

    # --- Display ---
    digest_text = format_digest(article_data, wishlist_matches)
    print(digest_text)

    # --- Save ---
    if do_save:
        path = save_digest(digest_text)
        print(f"Digest saved to {path}")


def _fetch_latest_discounts(source="reddit"):
    """Fetch and return (article_data, discounts_list) from the latest update.

    ``discounts_list`` is normalised so each entry has numeric ``discount``
    (int) and ``item`` (str) keys suitable for the ROI/comparison APIs.
    """
    article_data = None

    if source in ("reddit", "auto"):
        result = reddit_fetch()
        if result and (result.get("discounts") or result.get("podium_vehicle")):
            article_data = result

    if article_data is None:
        weekly = get_latest_weekly_update()
        if weekly is None:
            return None, []
        parsed = parse_full_article(weekly["url"], blurb=weekly.get("blurb", ""))
        article_data = parsed if parsed else {"discounts": [], "bonuses": [], "podium_vehicle": None}

    raw_discounts = article_data.get("discounts", [])
    normalised = []
    for d in raw_discounts:
        pct_str = str(d.get("discount", "0"))
        m = re.search(r"(\d+)", pct_str)
        pct = int(m.group(1)) if m else 0
        normalised.append({
            "item": d.get("item", ""),
            "discount": pct,
            "category": d.get("category", "other"),
        })
    return article_data, normalised


def _roi_recommendation_label(roi_str):
    """Map a 30-day ROI percentage string to a recommendation label."""
    m = re.search(r"(\d+)", str(roi_str))
    if not m:
        return "SITUATIONAL"
    val = int(m.group(1))
    if val >= 200:
        return "STRONG BUY"
    if val >= 100:
        return "BUY"
    if val >= 50:
        return "GOOD VALUE"
    return "SITUATIONAL"


# ---------------------------------------------------------------------------
# ROI command
# ---------------------------------------------------------------------------


def cmd_roi(args):
    """Calculate ROI for a single discounted item."""
    prices_db = load_prices()
    item_name = args.item
    discount = args.discount

    savings = calculate_discount_savings(item_name, discount, prices_db)
    if not savings:
        print(f"Item '{item_name}' not found in the price database.")
        print("Use 'python main.py price search <name>' to check available items.")
        sys.exit(1)

    name = savings["item"]
    sale_price = savings["best_price"]

    print(f"\nROI Analysis: {name} ({int(discount)}% off)")
    print("=" * 40)
    print(f"  Base Price:        {format_currency(savings['base_price'])}")
    print(f"  Discount:          {int(discount)}%")
    print(f"  Sale Price:        {format_currency(sale_price)}")
    print(f"  Savings:           {format_currency(savings['savings_vs_base'])}")

    # Check heist ROI
    heist = None
    for hname, hinfo in prices_db.get("heists", {}).items():
        for req in hinfo.get("requirements", []):
            if req.lower() in name.lower() or name.lower() in req.lower():
                heist = calculate_heist_roi(hname, prices_db=prices_db)
                break
        if heist:
            break

    biz = calculate_business_roi(name, prices_db)

    if heist:
        payout = heist["avg_payout_per_run"]
        time_min = heist["avg_time_per_run_minutes"]
        break_even = round(sale_price / payout, 2) if payout else 0
        roi_label = heist["roi_30_days"]

        print(f"\n  Income Potential:")
        print(f"  Avg Heist Payout:  {format_currency(payout)}")
        print(f"  Avg Time:          {time_min} minutes")
        print(f"  Break-even:        {break_even} heist runs")
        print(f"\n  30-Day ROI:        {roi_label}")
        print(f"  Recommendation:    {_roi_recommendation_label(roi_label)}")

    elif biz:
        hourly = biz["avg_hourly_profit"]
        roi_label = biz["roi_30_days"]

        print(f"\n  Income Potential:")
        print(f"  Income Type:       {biz['income_type'].capitalize()}")
        print(f"  Avg Hourly Profit: {format_currency(hourly)}")
        print(f"  Break-even:        {biz['break_even_hours']} hours ({biz['break_even_weeks']} weeks)")
        print(f"\n  30-Day ROI:        {roi_label}")
        print(f"  Recommendation:    {_roi_recommendation_label(roi_label)}")

    else:
        print(f"\n  Income Potential:  N/A (utility/combat item)")
        print(f"  Recommendation:    SITUATIONAL")

    print("=" * 40)
    print()


# ---------------------------------------------------------------------------
# Compare command
# ---------------------------------------------------------------------------


def cmd_compare(args):
    """Fetch latest update and compare all discounted items."""
    source = getattr(args, "source", "reddit")
    fmt = getattr(args, "format", "terminal")

    print("Fetching latest weekly update...")
    article_data, discounts = _fetch_latest_discounts(source)

    if not discounts:
        print("No discounts found in the latest update.")
        sys.exit(1)

    prices_db = load_prices()
    print(f"Found {len(discounts)} discounts. Generating comparison...\n")

    # Comparison table (shows all items, even those not in price DB)
    table = generate_comparison_table(discounts, prices_db, format=fmt)
    print(table)

    # Savings chart
    print()
    chart = generate_discount_chart(discounts, prices_db)
    print(chart)

    # Ranked investments (only items found in price DB)
    ranked = compare_investments(discounts, prices_db)
    if ranked:
        print(f"\nRanked by ROI (priced items):")
        print("-" * 40)
        for r in ranked:
            roi = r.get("roi_30_days", "N/A")
            print(f"  {r['rank']}. {r['item']} \u2014 {int(r['discount_percent'])}% off"
                  f" \u2014 ROI: {roi}")
            if r.get("reason"):
                print(f"     {r['reason']}")

    # Count items not in price DB and show a helpful note
    known_count = len(ranked) if ranked else 0
    unknown_count = len(discounts) - known_count
    if unknown_count > 0:
        print(f"\n  Note: {unknown_count} item(s) not in price database."
              f" Use 'python main.py price add' to add them.")

    print()


# ---------------------------------------------------------------------------
# Recommend command
# ---------------------------------------------------------------------------


def cmd_recommend(args):
    """Get purchase recommendations based on budget and playstyle."""
    budget = args.budget
    playstyle = args.playstyle
    source = getattr(args, "source", "reddit")

    print(f"Fetching latest weekly update...")
    article_data, discounts = _fetch_latest_discounts(source)

    if not discounts:
        print("No discounts found in the latest update.")
        sys.exit(1)

    prices_db = load_prices()
    rec = generate_purchase_recommendation(discounts, budget, prices_db, playstyle)

    print(f"\nBudget: {format_currency(budget)} | Playstyle: {playstyle.capitalize()}")
    print("=" * 40)

    if rec["recommendations"]:
        # Group by priority
        high = [r for r in rec["recommendations"] if r["priority"] == "HIGH"]
        medium = [r for r in rec["recommendations"] if r["priority"] == "MEDIUM"]
        low = [r for r in rec["recommendations"] if r["priority"] == "LOW"]

        idx = 1
        if high:
            print(f"\n\U0001f525 HIGH PRIORITY:")
            for r in high:
                roi_str = f" — ROI: {r['roi_30_days']}" if r.get("roi_30_days") else ""
                print(f"  {idx}. {r['item']} ({format_currency(r['discounted_price'])}) - "
                      f"{r['discount_percent']}% off")
                print(f"     \u2192 {r['reason']}{roi_str}")
                idx += 1

        if medium:
            print(f"\n\U0001f4a1 RECOMMENDED:")
            for r in medium:
                roi_str = f" — ROI: {r['roi_30_days']}" if r.get("roi_30_days") else ""
                print(f"  {idx}. {r['item']} ({format_currency(r['discounted_price'])}) - "
                      f"{r['discount_percent']}% off")
                print(f"     \u2192 {r['reason']}{roi_str}")
                idx += 1

        if low:
            print(f"\n  ALSO CONSIDER:")
            for r in low:
                print(f"  {idx}. {r['item']} ({format_currency(r['discounted_price'])}) - "
                      f"{r['discount_percent']}% off")
                print(f"     \u2192 {r['reason']}")
                idx += 1
    else:
        print("\n  No recommendations within budget.")

    print(f"\n  Total:     {format_currency(rec['total_cost'])}")
    print(f"  Remaining: {format_currency(rec['remaining_budget'])}")

    if rec.get("alternative_options"):
        print(f"\n  Over Budget:")
        for alt in rec["alternative_options"]:
            print(f"    - {alt['item']} ({format_currency(alt['discounted_price'])}) "
                  f"- {alt['discount_percent']}% off")

    print("=" * 40)
    print()


# ---------------------------------------------------------------------------
# Check-ROI command (enhanced check)
# ---------------------------------------------------------------------------


def cmd_check_roi(args):
    """Enhanced 'check' that includes ROI analysis for discounts."""
    source = getattr(args, "source", "reddit")
    do_save = getattr(args, "save", False)
    budget = getattr(args, "budget", None)

    # --- Fetch article (same as cmd_check) ---
    article_data = None

    if source in ("reddit", "auto"):
        print("Fetching latest weekly update from r/gtaonline...")
        result = reddit_fetch()
        if result and (result.get("discounts") or result.get("podium_vehicle")):
            print(f"Source: Reddit \u2014 {result['title']}")
            print(f"URL: {result['source_url']}")
            article_data = result
        elif source == "reddit":
            print("Reddit source had no detailed data, trying Rockstar API...")

    if article_data is None:
        print("Fetching latest GTA Online newswire...")
        weekly = get_latest_weekly_update()
        if weekly is None:
            print("Could not find a recent weekly update article.")
            sys.exit(1)
        print(f"Latest weekly update: {weekly['title']}")
        parsed = parse_full_article(weekly["url"], blurb=weekly.get("blurb", ""))
        article_data = parsed if parsed else {"discounts": [], "bonuses": [], "podium_vehicle": None}

    # --- Wishlist matching ---
    wishlist = load_wishlist()
    wishlist_matches = match_discounts(wishlist, article_data.get("discounts", []))

    # --- Display base digest ---
    digest_text = format_digest(article_data, wishlist_matches)
    print(digest_text)

    # --- ROI analysis ---
    raw_discounts = article_data.get("discounts", [])
    if raw_discounts:
        normalised = []
        for d in raw_discounts:
            pct_str = str(d.get("discount", "0"))
            m = re.search(r"(\d+)", pct_str)
            pct = int(m.group(1)) if m else 0
            normalised.append({"item": d.get("item", ""), "discount": pct})

        prices_db = load_prices()

        print("\nROI COMPARISON:")
        print("=" * 50)
        table = generate_comparison_table(normalised, prices_db)
        print(table)

        # Count how many items had price data
        priced = sum(
            1 for d in normalised
            if calculate_discount_savings(d["item"], d["discount"], prices_db)
        )
        unpriced = len(normalised) - priced
        if unpriced:
            print(f"\n  ({unpriced} item(s) not in price database — "
                  f"use 'python main.py price add' to add them)")

        print()
        chart = generate_discount_chart(normalised, prices_db)
        print(chart)

        # Purchase recommendations if budget provided
        if budget:
            rec = generate_purchase_recommendation(
                normalised, budget, prices_db,
            )
            print(f"\n\nPURCHASE RECOMMENDATIONS (Budget: {format_currency(budget)}):")
            print("-" * 50)
            for r in rec.get("recommendations", []):
                roi_str = f" | ROI: {r['roi_30_days']}" if r.get("roi_30_days") else ""
                print(f"  [{r['priority']}] {r['item']} "
                      f"({format_currency(r['discounted_price'])}){roi_str}")
                print(f"       {r['reason']}")
            print(f"\n  Total: {format_currency(rec['total_cost'])} | "
                  f"Remaining: {format_currency(rec['remaining_budget'])}")

        print()

    # --- Save ---
    if do_save:
        path = save_digest(digest_text)
        print(f"Digest saved to {path}")


def cmd_list(args):
    """Show recent GTA Online newswire articles."""
    result = fetch_newswire_articles(page=1)
    if result is None:
        print("Failed to fetch articles. Check your internet connection.")
        sys.exit(1)

    articles = result["articles"]
    print(f"\nLatest GTA Online articles ({len(articles)} results):\n")
    for i, art in enumerate(articles, 1):
        print(f"  {i:2d}. [{art['date']}] {art['title']}")
        print(f"      {art['url']}")


def cmd_test(args):
    """Run the scraper integration test."""
    success = test_scraper()
    sys.exit(0 if success else 1)


def cmd_test_parser(args):
    """Run the parser integration test."""
    success = test_parser()
    sys.exit(0 if success else 1)


def cmd_test_reddit(args):
    """Run the Reddit scraper integration test."""
    success = test_reddit_scraper()
    sys.exit(0 if success else 1)


def cmd_wiki_test(args):
    """Test wiki price lookup for a specific item (debug helper)."""
    import logging
    logging.basicConfig(level=logging.INFO)

    from src.wiki_lookup import (
        _search_wiki_page, _fetch_page_wikitext, _extract_prices_from_wikitext,
        _strip_manufacturer, lookup_price,
    )

    item = args.item
    print(f"\n=== Wiki Lookup Debug: '{item}' ===\n")

    stripped = _strip_manufacturer(item)
    if stripped != item:
        print(f"  Manufacturer stripped: '{item}' → '{stripped}'")
    else:
        print(f"  No manufacturer prefix detected")

    print(f"\n--- Step 1: Search for wiki page ---")
    page_title = _search_wiki_page(item)
    print(f"  Page found: {page_title}")
    if not page_title:
        print("  FAILED: no wiki page found")
        return

    print(f"\n--- Step 2: Fetch wikitext ---")
    wikitext = _fetch_page_wikitext(page_title)
    if not wikitext:
        print("  FAILED: could not fetch wikitext")
        return
    print(f"  Wikitext length: {len(wikitext)} chars")

    # Show first few lines and any lines with price-related content
    lines = wikitext.splitlines()
    print(f"  First 5 lines:")
    for line in lines[:5]:
        print(f"    {line[:120]}")

    print(f"\n  Price-related lines:")
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(kw in lower for kw in ["price", "cost", "trade", "$", "gta$",
                                       "purchase", "bought", "available"]):
            print(f"    L{i+1}: {line[:150]}")

    print(f"\n--- Step 3: Extract prices ---")
    prices = _extract_prices_from_wikitext(wikitext)
    if prices:
        print(f"  Base price:  ${prices['base_price']:,}")
        if prices.get("trade_price"):
            print(f"  Trade price: ${prices['trade_price']:,}")
        print(f"  Type:        {prices.get('type', 'unknown')}")
    else:
        print("  FAILED: no prices extracted from wikitext")

    # Also show what the full lookup_price returns
    print(f"\n--- Full lookup_price result ---")
    result = lookup_price(item)
    if result:
        for k, v in result.items():
            if isinstance(v, int):
                print(f"  {k}: ${v:,}")
            else:
                print(f"  {k}: {v}")
    else:
        print("  None")
    print()


def cmd_dump(args):
    """Dump cleaned Reddit post text for debugging."""
    from src.reddit_scraper import get_latest_weekly_post, _strip_markdown, _split_sections
    import logging
    logging.basicConfig(level=logging.WARNING)

    post = get_latest_weekly_post()
    if not post:
        print("No post found")
        sys.exit(1)

    cleaned = _strip_markdown(post["selftext"])
    print("=== CLEANED TEXT (all lines) ===")
    for i, line in enumerate(cleaned.splitlines(), 1):
        print(f"{i:3d} | {line}")

    print("\n=== SECTIONS ===")
    for hdr, body in _split_sections(cleaned):
        print(f"\n--- [{hdr or '(no header)'}] ---")
        for bline in body.splitlines()[:10]:
            print(f"  {bline}")


def cmd_wishlist_add(args):
    """Add an item to the wishlist."""
    add_item(args.category, args.name, args.priority)


def cmd_wishlist_remove(args):
    """Remove an item from the wishlist."""
    remove_item(args.category, args.name)


def cmd_wishlist_list(args):
    """List all wishlist items."""
    list_wishlist()


def cmd_price_lookup(args):
    """Look up an item's price."""
    result = get_item_price(args.name)
    if result:
        print(format_price_info(result))
    else:
        print(f"'{args.name}' not found in price database.")


def cmd_price_search(args):
    """Search for items in the price database."""
    results = search_items(args.query)
    if not results:
        print(f"No items matching '{args.query}'.")
        return
    print(f"\nFound {len(results)} result(s):\n")
    for item in results:
        print(format_price_info(item))
        print()


def cmd_price_add(args):
    """Add an item to the price database."""
    kwargs = {}
    if args.trade_price is not None:
        kwargs["trade_price"] = args.trade_price
    if args.max_price is not None:
        kwargs["max_price"] = args.max_price
    if args.type is not None:
        kwargs["type"] = args.type
    if args.notes is not None:
        kwargs["notes"] = args.notes
    add_item_price(args.category, args.name, args.base_price, **kwargs)


def cmd_price_update(args):
    """Update an item in the price database."""
    kwargs = {}
    if args.base_price is not None:
        kwargs["base_price"] = args.base_price
    if args.trade_price is not None:
        kwargs["trade_price"] = args.trade_price
    if args.max_price is not None:
        kwargs["max_price"] = args.max_price
    if args.type is not None:
        kwargs["type"] = args.type
    if args.notes is not None:
        kwargs["notes"] = args.notes
    if not kwargs:
        print("No fields to update. Use --base-price, --trade-price, --notes, etc.")
        return
    update_item_price(args.name, **kwargs)


# ---------------------------------------------------------------------------
# CLI structure
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="GTA Newswire Tracker - Track GTA Online weekly updates",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # check
    check_parser = subparsers.add_parser(
        "check", help="Fetch and display the latest weekly update",
    )
    check_parser.add_argument(
        "--source", choices=["reddit", "rockstar", "auto"],
        default="reddit",
        help="Data source (default: reddit)",
    )
    check_parser.add_argument(
        "--save", action="store_true",
        help="Save digest to data/digest_YYYY-MM-DD.txt",
    )
    check_parser.set_defaults(func=cmd_check)

    # roi
    roi_parser = subparsers.add_parser(
        "roi", help="Calculate ROI for a discounted item",
    )
    roi_parser.add_argument(
        "--item", required=True,
        help='Item name, e.g. "Kosatka"',
    )
    roi_parser.add_argument(
        "--discount", type=float, required=True,
        help="Discount percentage, e.g. 30",
    )
    roi_parser.set_defaults(func=cmd_roi)

    # compare
    compare_parser = subparsers.add_parser(
        "compare", help="Compare all discounted items from latest update",
    )
    compare_parser.add_argument(
        "--source", choices=["reddit", "rockstar", "auto"],
        default="reddit",
        help="Data source (default: reddit)",
    )
    compare_parser.add_argument(
        "--format", choices=["terminal", "markdown", "csv"],
        default="terminal",
        help="Output format (default: terminal)",
    )
    compare_parser.set_defaults(func=cmd_compare)

    # recommend
    recommend_parser = subparsers.add_parser(
        "recommend", help="Get purchase recommendations for a budget",
    )
    recommend_parser.add_argument(
        "--budget", type=int, required=True,
        help="Available GTA$ budget, e.g. 5000000",
    )
    recommend_parser.add_argument(
        "--playstyle", choices=["solo", "crew", "grinder", "casual", "mixed"],
        default="mixed",
        help="Playstyle (default: mixed)",
    )
    recommend_parser.add_argument(
        "--source", choices=["reddit", "rockstar", "auto"],
        default="reddit",
        help="Data source (default: reddit)",
    )
    recommend_parser.set_defaults(func=cmd_recommend)

    # check-roi
    check_roi_parser = subparsers.add_parser(
        "check-roi", help="Enhanced weekly check with ROI analysis",
    )
    check_roi_parser.add_argument(
        "--source", choices=["reddit", "rockstar", "auto"],
        default="reddit",
        help="Data source (default: reddit)",
    )
    check_roi_parser.add_argument(
        "--budget", type=int, default=None,
        help="Optional budget for purchase recommendations",
    )
    check_roi_parser.add_argument(
        "--save", action="store_true",
        help="Save digest to data/digest_YYYY-MM-DD.txt",
    )
    check_roi_parser.set_defaults(func=cmd_check_roi)

    # list
    list_parser = subparsers.add_parser(
        "list", help="Show recent GTA Online articles",
    )
    list_parser.set_defaults(func=cmd_list)

    # test
    test_parser_cmd = subparsers.add_parser(
        "test", help="Run scraper integration test",
    )
    test_parser_cmd.set_defaults(func=cmd_test)

    # test-parser
    tp_parser = subparsers.add_parser(
        "test-parser", help="Run parser integration test",
    )
    tp_parser.set_defaults(func=cmd_test_parser)

    # test-reddit
    tr_parser = subparsers.add_parser(
        "test-reddit", help="Run Reddit scraper test",
    )
    tr_parser.set_defaults(func=cmd_test_reddit)

    # wiki-test (debug)
    wt_parser = subparsers.add_parser(
        "wiki-test", help="Debug wiki price lookup for a specific item",
    )
    wt_parser.add_argument("item", help='Item name, e.g. "Vapid Slamtruck"')
    wt_parser.set_defaults(func=cmd_wiki_test)

    # dump (debug)
    dump_parser = subparsers.add_parser(
        "dump", help="Dump cleaned Reddit post text for debugging",
    )
    dump_parser.set_defaults(func=cmd_dump)

    # wishlist
    wish_parser = subparsers.add_parser(
        "wishlist", help="Manage your wishlist (add/remove/list)",
    )
    wish_sub = wish_parser.add_subparsers(dest="wishlist_command")

    # wishlist add
    add_p = wish_sub.add_parser("add", help="Add an item to your wishlist")
    add_p.add_argument("name", help="Item name to add")
    add_p.add_argument(
        "-c", "--category",
        default="other",
        choices=["vehicles", "properties", "weapons", "other"],
        help="Wishlist category (default: other)",
    )
    add_p.add_argument(
        "-p", "--priority",
        type=int, default=3, choices=range(1, 6),
        metavar="1-5",
        help="Priority 1-5 where 5 is highest (default: 3)",
    )
    add_p.set_defaults(func=cmd_wishlist_add)

    # wishlist remove
    rm_p = wish_sub.add_parser("remove", help="Remove an item from your wishlist")
    rm_p.add_argument("name", help="Item name to remove")
    rm_p.add_argument(
        "-c", "--category",
        default="other",
        choices=["vehicles", "properties", "weapons", "other"],
        help="Wishlist category (default: other)",
    )
    rm_p.set_defaults(func=cmd_wishlist_remove)

    # wishlist list
    list_p = wish_sub.add_parser("list", help="List all wishlist items")
    list_p.set_defaults(func=cmd_wishlist_list)

    # price
    price_parser = subparsers.add_parser(
        "price", help="Look up or manage the price database",
    )
    price_sub = price_parser.add_subparsers(dest="price_command")

    # price lookup
    plook = price_sub.add_parser("lookup", help="Look up an item's price")
    plook.add_argument("name", help="Item name to look up")
    plook.set_defaults(func=cmd_price_lookup)

    # price search
    psearch = price_sub.add_parser("search", help="Search for items by name")
    psearch.add_argument("query", help="Search query")
    psearch.set_defaults(func=cmd_price_search)

    # price add
    padd = price_sub.add_parser("add", help="Add an item to the price database")
    padd.add_argument("name", help="Item name")
    padd.add_argument("base_price", type=int, help="Base price in GTA$")
    padd.add_argument(
        "-c", "--category",
        default="vehicles",
        choices=["vehicles", "properties", "heists"],
        help="Category (default: vehicles)",
    )
    padd.add_argument("--trade-price", type=int, default=None, help="Trade price")
    padd.add_argument("--max-price", type=int, default=None, help="Max price (properties)")
    padd.add_argument("--type", default=None, help="Item type (e.g. helicopter, business)")
    padd.add_argument("--notes", default=None, help="Additional notes")
    padd.set_defaults(func=cmd_price_add)

    # price update
    pupd = price_sub.add_parser("update", help="Update an item's price info")
    pupd.add_argument("name", help="Item name to update")
    pupd.add_argument("--base-price", type=int, default=None, help="New base price")
    pupd.add_argument("--trade-price", type=int, default=None, help="New trade price")
    pupd.add_argument("--max-price", type=int, default=None, help="New max price")
    pupd.add_argument("--type", default=None, help="New item type")
    pupd.add_argument("--notes", default=None, help="New notes")
    pupd.set_defaults(func=cmd_price_update)

    # --- Dispatch ---
    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    elif args.command == "wishlist":
        wish_parser.print_help()
    elif args.command == "price":
        price_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
