#!/usr/bin/env python3
"""GTA Newswire Tracker - Entry point.

Track GTA Online weekly updates, discounts, events, and check your wishlist.

Commands:
    check        Fetch latest weekly update and display digest
    list         Show recent GTA Online articles
    test         Run scraper integration test
    test-parser  Run parser integration test
    wishlist     Manage wishlist (add/remove/list)
"""

import argparse
import sys

from src.scraper import fetch_newswire_articles, get_latest_weekly_update, test_scraper
from src.reddit_scraper import fetch_weekly_update as reddit_fetch, test_reddit_scraper
from src.parser import parse_full_article, test_parser
from src.wishlist import (
    add_item, remove_item, list_wishlist,
    load_wishlist, match_discounts,
)
from src.digest import format_digest, print_digest, save_digest


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

    # --- Dispatch ---
    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    elif args.command == "wishlist":
        wish_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
