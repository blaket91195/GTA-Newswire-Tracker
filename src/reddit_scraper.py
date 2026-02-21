"""Reddit-based scraper for GTA Online weekly update info.

Fetches weekly update posts from r/gtaonline using Reddit's public
JSON API (no authentication required).  The community posts contain
structured markdown with discounts, bonuses, podium vehicles, and more
— much easier to parse than Rockstar's JS-heavy site.
"""

import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reddit API settings
# ---------------------------------------------------------------------------

SUBREDDIT = "gtaonline"

SEARCH_URL = (
    "https://www.reddit.com/r/{subreddit}/search.json"
)

HEADERS = {
    "User-Agent": "GTA-Newswire-Tracker/1.0 (weekly update digest tool)",
}

# Search queries to try, in order of preference
SEARCH_QUERIES = [
    "weekly bonuses discounts",
    "weekly update",
    "weekly discounts podium",
]

# Keywords that indicate a post is a weekly update summary
WEEKLY_POST_KEYWORDS = [
    "weekly", "bonuses", "discounts", "podium", "prize ride",
    "double", "triple", "2x", "3x",
]

# Max age in days for a weekly update post to be considered current
MAX_POST_AGE_DAYS = 8


# ---------------------------------------------------------------------------
# Reddit API fetching
# ---------------------------------------------------------------------------


def _reddit_get(url, params=None):
    """Make a GET request to Reddit's JSON API with rate-limit handling."""
    try:
        resp = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            logger.warning("Reddit rate limit hit, waiting %ds", retry_after)
            time.sleep(retry_after)
            resp = requests.get(
                url, params=params, headers=HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Reddit API request failed: %s", exc)
        return None


def search_weekly_posts(query=None, limit=10):
    """Search r/gtaonline for weekly update posts.

    Args:
        query: Search query string. If None, tries multiple queries.
        limit: Max results to return.

    Returns:
        List of post dicts with keys: title, selftext, url, created_utc,
        author, score, permalink.
    """
    queries = [query] if query else SEARCH_QUERIES

    for q in queries:
        logger.info("Searching r/%s for: %s", SUBREDDIT, q)
        data = _reddit_get(
            SEARCH_URL.format(subreddit=SUBREDDIT),
            params={
                "q": q,
                "sort": "new",
                "restrict_sr": "on",
                "limit": str(limit),
                "t": "month",
            },
        )

        if data is None:
            continue

        children = data.get("data", {}).get("children", [])
        posts = []
        for child in children:
            post = child.get("data", {})
            # Skip posts with no selftext (link-only posts)
            if not post.get("selftext"):
                continue
            posts.append({
                "title": post.get("title", ""),
                "selftext": post.get("selftext", ""),
                "url": f"https://www.reddit.com{post.get('permalink', '')}",
                "created_utc": post.get("created_utc", 0),
                "author": post.get("author", ""),
                "score": post.get("score", 0),
            })

        if posts:
            logger.info("Found %d posts for query '%s'", len(posts), q)
            return posts

    logger.warning("No weekly update posts found on Reddit")
    return []


def get_latest_weekly_post():
    """Find the most recent weekly update post from r/gtaonline.

    Returns:
        Post dict with title, selftext, url, etc., or None.
    """
    import datetime

    posts = search_weekly_posts()
    if not posts:
        return None

    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    max_age = MAX_POST_AGE_DAYS * 86400

    # Score posts by relevance
    best = None
    best_score = -1

    for post in posts:
        title_lower = post["title"].lower()
        text_lower = post["selftext"].lower()

        # Must contain at least 2 weekly keywords in title or body
        keyword_hits = sum(
            1 for kw in WEEKLY_POST_KEYWORDS
            if kw in title_lower or kw in text_lower
        )
        if keyword_hits < 2:
            continue

        # Skip old posts
        age = now - post["created_utc"]
        if age > max_age:
            continue

        # Prefer posts with more structured content (more lines = more detail)
        line_count = len(post["selftext"].splitlines())
        score = keyword_hits * 10 + min(line_count, 50) + post["score"] / 100

        # Bonus for having discount percentages in body
        if re.search(r"\d+%", post["selftext"]):
            score += 20

        # Bonus for having section headers
        if re.search(r"(?:^|\n)#+\s", post["selftext"]):
            score += 15

        if score > best_score:
            best_score = score
            best = post

    if best:
        logger.info("Best weekly post: %s (score=%.1f)", best["title"], best_score)
    else:
        logger.warning("No suitable weekly update post found")

    return best


# ---------------------------------------------------------------------------
# Markdown parsing — extract structured weekly info
# ---------------------------------------------------------------------------


def _split_sections(text):
    """Split markdown text into sections by headers.

    Returns:
        List of (header, body) tuples. The first entry may have
        header="" for content before the first header.
    """
    sections = []
    current_header = ""
    current_lines = []

    for line in text.splitlines():
        # Match markdown headers: # Header, ## Header, ### Header
        header_match = re.match(r"^#{1,4}\s+(.+)", line)
        # Also match bold-as-header: **Header**
        bold_match = re.match(r"^\*\*([^*]+)\*\*\s*$", line)

        if header_match or bold_match:
            # Save previous section
            if current_header or current_lines:
                sections.append((current_header, "\n".join(current_lines)))
            current_header = (header_match.group(1) if header_match
                              else bold_match.group(1)).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_header or current_lines:
        sections.append((current_header, "\n".join(current_lines)))

    return sections


def _find_section(sections, keywords):
    """Find a section whose header matches any of the given keywords.

    Args:
        sections: List of (header, body) tuples.
        keywords: List of keyword strings to match (case-insensitive).

    Returns:
        Section body string, or None.
    """
    for header, body in sections:
        header_lower = header.lower()
        if any(kw in header_lower for kw in keywords):
            return body
    return None


def parse_reddit_discounts(text):
    """Extract discount items and percentages from Reddit post text.

    Handles formats like:
    - "30% off the Insurgent Pick-Up"
    - "Insurgent Pick-Up — 30% off"
    - "- Insurgent Pick-Up (30% off)"
    - "| Vehicle | 30% |"

    Returns:
        List of dicts: [{"item": ..., "discount": ..., "category": ...}]
    """
    discounts = []
    seen = set()

    patterns = [
        # "30% off the Insurgent Pick-Up"
        re.compile(
            r"(\d{1,2})%\s+off\s+(?:the\s+|all\s+)?(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE,
        ),
        # "Insurgent Pick-Up — 30% off"
        re.compile(
            r"[-•*]\s*(.+?)\s*[–—\-]+\s*(\d{1,2})%\s+off",
            re.IGNORECASE,
        ),
        # "Insurgent Pick-Up (30% off)"
        re.compile(
            r"[-•*]\s*(.+?)\s*\((\d{1,2})%\s*(?:off|discount)\)",
            re.IGNORECASE,
        ),
        # "- 30% off: Insurgent Pick-Up"
        re.compile(
            r"[-•*]\s*(\d{1,2})%\s*off[:\s]+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE,
        ),
        # Table format: "| Insurgent Pick-Up | 30% |"
        re.compile(
            r"\|\s*(.+?)\s*\|\s*(\d{1,2})%\s*\|",
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(text):
            groups = match.groups()
            # Figure out which group is item vs percentage
            if groups[0].isdigit() or (len(groups[0]) <= 3 and groups[0].rstrip('%').isdigit()):
                pct, item = groups[0], groups[1]
            elif groups[1].isdigit() or (len(groups[1]) <= 3 and groups[1].rstrip('%').isdigit()):
                item, pct = groups[0], groups[1]
            else:
                continue

            item = item.strip().rstrip(".,;:–—-*").strip()
            pct = pct.rstrip("%")

            if not item or len(item) < 3:
                continue

            key = item.lower()
            if key not in seen:
                seen.add(key)
                discounts.append({
                    "item": item,
                    "discount": f"{pct}%",
                    "category": _guess_category(item),
                })

    return discounts


def parse_reddit_bonuses(text):
    """Extract 2X/3X bonus events from Reddit post text.

    Returns:
        List of bonus description strings.
    """
    bonuses = []
    seen = set()

    patterns = [
        # "2X GTA$ & RP on Counterfeit Cash"
        re.compile(
            r"(\d)[Xx]\s+(?:GTA\$?\s*(?:and|&)\s*RP|Rewards?|GTA\$?|RP)"
            r"\s+(?:on|in|from|for)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE,
        ),
        # "Double/Triple on Counterfeit Cash"
        re.compile(
            r"(Double|Triple|Quadruple)\s+(?:GTA\$?\s*(?:and|&)\s*RP|Rewards?|payouts?)"
            r"\s+(?:on|in|from|for)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE,
        ),
        # "2X on Counterfeit Cash"
        re.compile(
            r"(\d)[Xx]\s+(?:on|in|from)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE,
        ),
        # "- Counterfeit Cash (2X)" or "Counterfeit Cash — Double"
        re.compile(
            r"[-•*]\s*(.+?)\s*(?:\(|[–—\-]+\s*)(\d[Xx]|Double|Triple)",
            re.IGNORECASE,
        ),
    ]

    mult_map = {"double": "2X", "triple": "3X", "quadruple": "4X"}

    for pattern in patterns:
        for match in pattern.finditer(text):
            groups = match.groups()
            mult, activity = groups[0], groups[1]

            # Normalise multiplier
            mult_lower = mult.lower().strip()
            if mult_lower in mult_map:
                mult = mult_map[mult_lower]
            elif mult_lower[0].isdigit():
                mult = mult_lower[0] + "X"

            activity = activity.strip().rstrip(".,;:–—-*()").strip()
            if not activity or len(activity) < 3:
                continue

            key = activity.lower()
            if key not in seen:
                seen.add(key)
                bonuses.append(f"{mult} on {activity}")

    return bonuses


def parse_reddit_podium(text):
    """Extract the podium/prize ride vehicle from Reddit post text.

    Returns:
        Dict with 'podium_vehicle' and 'prize_ride' keys (str or None).
    """
    result = {"podium_vehicle": None, "prize_ride": None}

    podium_patterns = [
        re.compile(r"Podium\s+Vehicle[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
        re.compile(r"Lucky\s+Wheel[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
        re.compile(r"Podium\s+(?:Car|Vehicle)\s*:\s*(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
        re.compile(r"[-•*]\s*(?:\*\*)?Podium(?:\s+Vehicle)?(?:\*\*)?[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
    ]

    prize_patterns = [
        re.compile(r"Prize\s+Ride[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
        re.compile(r"Prize\s+Ride\s+(?:Vehicle|Car)[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
        re.compile(r"[-•*]\s*(?:\*\*)?Prize\s+Ride(?:\*\*)?[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
    ]

    test_track_patterns = [
        re.compile(r"Test\s+Track[:\s–—\-]+(.+?)(?:\s*[\|,\n]|$)", re.IGNORECASE),
    ]

    for pattern in podium_patterns:
        match = pattern.search(text)
        if match:
            vehicle = match.group(1).strip().rstrip(".,;:–—-*").strip()
            if vehicle and len(vehicle) > 2:
                result["podium_vehicle"] = vehicle
                break

    for pattern in prize_patterns:
        match = pattern.search(text)
        if match:
            vehicle = match.group(1).strip().rstrip(".,;:–—-*").strip()
            if vehicle and len(vehicle) > 2:
                result["prize_ride"] = vehicle
                break

    for pattern in test_track_patterns:
        match = pattern.search(text)
        if match:
            vehicle = match.group(1).strip().rstrip(".,;:–—-*").strip()
            if vehicle and len(vehicle) > 2:
                result["test_track"] = vehicle
                break

    return result


def _guess_category(item_name):
    """Guess the discount item category from its name."""
    lower = item_name.lower()
    vehicle_hints = [
        "car", "bike", "motorcycle", "helicopter", "plane", "jet",
        "truck", "suv", "van", "boat", "aircraft",
    ]
    property_hints = [
        "apartment", "garage", "office", "nightclub", "arcade",
        "facility", "bunker", "hangar", "warehouse", "agency",
        "factory", "clubhouse", "auto shop", "property",
    ]
    weapon_hints = [
        "weapon", "gun", "rifle", "pistol", "shotgun", "smg",
        "sniper", "launcher", "mk ii",
    ]

    if any(h in lower for h in weapon_hints):
        return "weapon"
    if any(h in lower for h in property_hints):
        return "property"
    if any(h in lower for h in vehicle_hints):
        return "vehicle"
    return "other"


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------


def parse_reddit_post(post):
    """Parse a Reddit weekly update post into structured data.

    Args:
        post: Dict with at least 'selftext' and 'title' keys.

    Returns:
        Dict with keys: discounts, bonuses, podium_vehicle, prize_ride,
        test_track, raw_text, source_url.
    """
    text = post["selftext"]
    title = post.get("title", "")

    # Parse from the full text (including title for context)
    full_text = title + "\n\n" + text

    # Try section-based parsing first
    sections = _split_sections(text)

    # Look for discount section
    discount_section = _find_section(sections, [
        "discount", "sale", "% off", "price",
    ])
    # Look for bonus section
    bonus_section = _find_section(sections, [
        "bonus", "double", "triple", "2x", "3x", "multiplier",
        "payout", "reward",
    ])

    # Parse discounts from discount section if found, otherwise full text
    discounts = parse_reddit_discounts(discount_section or full_text)

    # Parse bonuses from bonus section if found, otherwise full text
    bonuses = parse_reddit_bonuses(bonus_section or full_text)

    # Parse vehicles from full text (they could be in any section)
    vehicles = parse_reddit_podium(full_text)

    return {
        "discounts": discounts,
        "bonuses": bonuses,
        "podium_vehicle": vehicles.get("podium_vehicle"),
        "prize_ride": vehicles.get("prize_ride"),
        "test_track": vehicles.get("test_track"),
        "raw_text": text,
        "source_url": post.get("url", ""),
        "source": "reddit",
    }


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


def fetch_weekly_update():
    """Fetch and parse the latest GTA Online weekly update from Reddit.

    Returns:
        Parsed dict with discounts, bonuses, podium_vehicle, etc.,
        or None if no suitable post is found.
    """
    post = get_latest_weekly_post()
    if post is None:
        return None

    logger.info("Parsing Reddit post: %s", post["title"])
    result = parse_reddit_post(post)
    result["title"] = post["title"]
    result["date"] = post.get("created_utc", 0)
    result["author"] = post.get("author", "")

    logger.info(
        "Reddit parse: %d discounts, %d bonuses, podium=%s, prize_ride=%s",
        len(result["discounts"]),
        len(result["bonuses"]),
        result["podium_vehicle"] or "none",
        result.get("prize_ride") or "none",
    )

    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_reddit_scraper():
    """Test the Reddit scraper against live data."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("  GTA Newswire Tracker — Reddit Scraper Test")
    print("=" * 60)

    # Step 1: Search for posts
    print("\n[Step 1] Searching r/gtaonline for weekly update posts...")
    posts = search_weekly_posts()

    if not posts:
        print("  FAIL: No posts found.")
        return False

    print(f"  Found {len(posts)} posts:")
    for i, p in enumerate(posts[:5], 1):
        print(f"  {i}. [{p['author']}] {p['title']}")
        print(f"     Score: {p['score']}  |  "
              f"Body: {len(p['selftext'])} chars")

    # Step 2: Get best weekly post
    print("\n[Step 2] Finding best weekly update post...")
    best = get_latest_weekly_post()

    if best is None:
        print("  No suitable weekly post found.")
        return False

    print(f"  Title:  {best['title']}")
    print(f"  Author: {best['author']}")
    print(f"  Score:  {best['score']}")
    print(f"  Body:   {len(best['selftext'])} chars")
    print(f"  URL:    {best['url']}")

    # Step 3: Parse it
    print("\n[Step 3] Parsing post content...")
    result = parse_reddit_post(best)

    print(f"\n  PODIUM VEHICLE: {result['podium_vehicle'] or 'Not found'}")
    print(f"  PRIZE RIDE: {result.get('prize_ride') or 'Not found'}")

    print(f"\n  BONUSES ({len(result['bonuses'])}):")
    for b in result["bonuses"]:
        print(f"    - {b}")

    print(f"\n  DISCOUNTS ({len(result['discounts'])}):")
    for d in result["discounts"]:
        print(f"    - {d['discount']} off {d['item']} [{d['category']}]")

    # Step 4: Show raw text preview
    print(f"\n[Step 4] Raw post text preview ({len(result['raw_text'])} chars):")
    preview = result["raw_text"][:500]
    for line in preview.splitlines()[:15]:
        print(f"  | {line}")

    print("\n" + "=" * 60)
    print("  Reddit scraper test complete.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_reddit_scraper()
