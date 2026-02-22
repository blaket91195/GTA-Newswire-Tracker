#!/usr/bin/env python3
"""GTA Newswire Tracker - Entry point.

Track GTA Online weekly updates, discounts, events, and check your wishlist.
"""

import argparse
import sys

from src.scraper import fetch_newswire_articles, get_latest_weekly_update, test_scraper
from src.reddit_scraper import fetch_weekly_update as reddit_fetch, test_reddit_scraper
from src.parser import parse_full_article, test_parser
from src.wishlist import add_item, remove_item, list_wishlist, check_discounts
from src.digest import print_digest


def cmd_check(args):
    """Fetch the latest weekly update and display the digest.

    Tries Reddit first (community posts have structured data), then
    falls back to the Rockstar Newswire API + article scraping.
    """
    source = getattr(args, "source", "reddit")

    if source in ("reddit", "auto"):
        print("Fetching latest weekly update from r/gtaonline...")
        result = reddit_fetch()

        if result and (result["discounts"] or result["podium_vehicle"]):
            print(f"Source: Reddit — {result['title']}")
            print(f"URL: {result['source_url']}")

            discount_items = [d["item"] for d in result.get("discounts", [])]
            wishlist_matches = check_discounts(discount_items)
            print_digest(result, wishlist_matches)
            return

        if source == "reddit":
            print("Reddit source had no detailed data, trying Rockstar API...")

    # Fallback: Rockstar Newswire API
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
        article_info = {"discounts": [], "bonuses": [], "podium_vehicle": None}
    else:
        article_info = parsed

    discount_items = [d["item"] for d in article_info.get("discounts", [])]
    wishlist_matches = check_discounts(discount_items)

    print_digest(article_info, wishlist_matches)


def cmd_list(args):
    """List recent GTA Online newswire articles."""
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


def cmd_wishlist_add(args):
    """Add an item to the wishlist."""
    add_item(args.name, args.category)


def cmd_wishlist_remove(args):
    """Remove an item from the wishlist."""
    remove_item(args.name, args.category)


def cmd_wishlist_list(args):
    """List all wishlist items."""
    list_wishlist()


def main():
    parser = argparse.ArgumentParser(
        description="GTA Newswire Tracker - Track GTA Online weekly updates"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # check command
    check_parser = subparsers.add_parser("check", help="Fetch and display the latest weekly update")
    check_parser.add_argument(
        "--source", choices=["reddit", "rockstar", "auto"],
        default="reddit",
        help="Data source: reddit (default), rockstar (API+scrape), auto (try both)",
    )

    # list command
    subparsers.add_parser("list", help="List recent GTA Online newswire articles")

    # test commands
    subparsers.add_parser("test", help="Run scraper integration test")
    subparsers.add_parser("test-parser", help="Run parser integration test")
    subparsers.add_parser("test-reddit", help="Run Reddit scraper test")
    subparsers.add_parser("dump", help="Dump cleaned Reddit post text for debugging")

    # wishlist commands
    wish_parser = subparsers.add_parser("wishlist", help="Manage your wishlist")
    wish_subparsers = wish_parser.add_subparsers(dest="wishlist_command")

    # wishlist add
    add_parser = wish_subparsers.add_parser("add", help="Add an item to your wishlist")
    add_parser.add_argument("name", help="Item name to add")
    add_parser.add_argument(
        "-c", "--category",
        default="other",
        choices=["vehicles", "properties", "weapons", "other"],
        help="Wishlist category (default: other)",
    )

    # wishlist remove
    rm_parser = wish_subparsers.add_parser("remove", help="Remove an item from your wishlist")
    rm_parser.add_argument("name", help="Item name to remove")
    rm_parser.add_argument(
        "-c", "--category",
        default="other",
        choices=["vehicles", "properties", "weapons", "other"],
        help="Wishlist category (default: other)",
    )

    # wishlist list
    wish_subparsers.add_parser("list", help="List all wishlist items")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "test-parser":
        cmd_test_parser(args)
    elif args.command == "test-reddit":
        success = test_reddit_scraper()
        sys.exit(0 if success else 1)
    elif args.command == "dump":
        from src.reddit_scraper import get_latest_weekly_post, _strip_markdown
        import logging
        logging.basicConfig(level=logging.WARNING)
        post = get_latest_weekly_post()
        if post:
            cleaned = _strip_markdown(post["selftext"])
            print("=== CLEANED TEXT (all lines) ===")
            for i, line in enumerate(cleaned.splitlines(), 1):
                print(f"{i:3d} | {line}")
            print(f"\n=== SECTIONS ===")
            from src.reddit_scraper import _split_sections
            for hdr, body in _split_sections(cleaned):
                print(f"\n--- [{hdr or '(no header)'}] ---")
                for bline in body.splitlines()[:10]:
                    print(f"  {bline}")
        else:
            print("No post found")
    elif args.command == "wishlist":
        if args.wishlist_command == "add":
            cmd_wishlist_add(args)
        elif args.wishlist_command == "remove":
            cmd_wishlist_remove(args)
        elif args.wishlist_command == "list":
            cmd_wishlist_list(args)
        else:
            wish_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
