#!/usr/bin/env python3
"""GTA Newswire Tracker - Entry point.

Track GTA Online weekly updates, discounts, events, and check your wishlist.
"""

import argparse
import sys

from src.scraper import fetch_newswire_page, get_latest_articles, fetch_article
from src.parser import parse_article
from src.wishlist import add_item, remove_item, list_wishlist, check_discounts
from src.digest import print_digest


def cmd_check(args):
    """Fetch the latest newswire and display the weekly digest."""
    print("Fetching latest GTA Online newswire...")
    soup = fetch_newswire_page()
    if soup is None:
        print("Failed to fetch newswire. Check your internet connection.")
        sys.exit(1)

    articles = get_latest_articles(soup)
    if not articles:
        print("No articles found on the newswire page.")
        sys.exit(1)

    # Fetch and parse the most recent article
    latest = articles[0]
    print(f"Latest article: {latest['title']}")
    print(f"URL: {latest['url']}")

    article_soup = fetch_article(latest["url"])
    article_info = parse_article(article_soup)

    # Check wishlist against discounts
    wishlist_matches = check_discounts(article_info["discounts"])

    print_digest(article_info, wishlist_matches)


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
    subparsers.add_parser("check", help="Fetch and display the latest weekly update")

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
