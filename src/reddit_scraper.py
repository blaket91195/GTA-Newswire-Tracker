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
# Markdown cleaning
# ---------------------------------------------------------------------------


def _strip_markdown(text):
    """Strip Reddit markdown formatting to get clean plain text.

    Handles:
    - [**Bold Link Text**](url)**:** value  → Bold Link Text: value
    - [Link Text](url)                      → Link Text
    - **bold**                               → bold
    - *italic*                               → italic
    - ~~strikethrough~~                      → strikethrough
    - &amp; and other HTML entities
    """
    # Step 1: Handle Reddit's complex link+bold patterns
    # [**Podium Vehicle**](url)**:** Karin Sultan RS Classic
    # → Podium Vehicle: Karin Sultan RS Classic
    text = re.sub(
        r'\[(?:\*\*)?([^]]*?)(?:\*\*)?\]\([^)]*\)(?:\*\*)?:?\s*',
        r'\1: ',
        text,
    )

    # Step 2: Clean up any remaining markdown links [text](url)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)

    # Step 3: Strip bold/italic markers
    text = re.sub(r'\*\*([^*]*)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]*)\*', r'\1', text)

    # Step 4: Strip strikethrough
    text = re.sub(r'~~([^~]*)~~', r'\1', text)

    # Step 5: HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&#39;', "'")
    text = text.replace('&quot;', '"')

    # Step 6: Clean up double colons/spaces from link stripping
    text = re.sub(r':\s*:', ':', text)
    text = re.sub(r'  +', ' ', text)

    return text


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
    - "Insurgent Pick-Up - $500,000 - 30% Discount"

    Returns:
        List of dicts: [{"item": ..., "discount": ..., "category": ...}]
    """
    discounts = []
    seen = set()

    # Reject items that are clearly not item names
    junk_re = re.compile(
        r"^(?:for|through|until|all|gta\+|members?|players?)$"
        r"|^(?:for\s+)?gta\+\s+members",
        re.IGNORECASE,
    )

    def _add(item, pct):
        item = item.strip().rstrip(".,;:–—-*").strip()
        # Strip leading bullet chars and whitespace
        item = re.sub(r"^[-•*>\s]+", "", item).strip()
        # Strip trailing price info: "Item - $500,000" → "Item"
        item = re.sub(r"\s*-\s*\$[\d,]+\s*$", "", item).strip()
        # Strip unbalanced trailing parens only
        if item.endswith(")") and item.count("(") < item.count(")"):
            item = item.rstrip(")")
        pct = pct.strip().rstrip("%")

        if not item or len(item) < 3 or not pct.isdigit():
            return
        if junk_re.search(item):
            return

        key = item.lower()
        if key not in seen:
            seen.add(key)
            discounts.append({
                "item": item,
                "discount": f"{pct}%",
                "category": _guess_category(item),
            })

    patterns = [
        # "30% off the Insurgent Pick-Up" / "30% off Insurgent"
        (re.compile(
            r"(\d{1,2})%\s+off\s+(?:the\s+|all\s+)?(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "pct_first"),
        # "Insurgent Pick-Up — 30% off"
        (re.compile(
            r"^[-•*>]?\s*(.+?)\s*[–—\-]+\s*(\d{1,2})%\s*(?:off|discount)",
            re.IGNORECASE | re.MULTILINE,
        ), "item_first"),
        # "Insurgent Pick-Up (30% off)"
        (re.compile(
            r"[-•*>]?\s*(.+?)\s*\((\d{1,2})%\s*(?:off|discount)\)",
            re.IGNORECASE,
        ), "item_first"),
        # "- 30% off: Insurgent Pick-Up"
        (re.compile(
            r"[-•*>]\s*(\d{1,2})%\s*off[:\s]+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "pct_first"),
        # Table format: "| Insurgent Pick-Up | 30% |" or "| Insurgent | $500,000 | 30% |"
        (re.compile(
            r"\|\s*([^|]+?)\s*\|[^|]*?(\d{1,2})%[^|]*\|",
        ), "item_first"),
        # "Item - $price - 30% Discount" (common Reddit table-like format)
        (re.compile(
            r"^[-•*>]?\s*(.+?)\s*-\s*\$[\d,]+\s*-\s*(\d{1,2})%",
            re.IGNORECASE | re.MULTILINE,
        ), "item_first"),
        # "Item ($price / 30% off)" or "Item ($price, 30% off)"
        (re.compile(
            r"[-•*>]?\s*(.+?)\s*\(\$[\d,]+\s*[/,]\s*(\d{1,2})%\s*(?:off|discount)?\)",
            re.IGNORECASE,
        ), "item_first"),
        # Line containing "X% Discount" with context: "Counterfeit Cash Factory: 40% Discount"
        (re.compile(
            r"^[-•*>]?\s*(.+?)\s*[:–—\-]+\s*(\d{1,2})%\s*Discount",
            re.IGNORECASE | re.MULTILINE,
        ), "item_first"),
    ]

    for pattern, order in patterns:
        for match in pattern.finditer(text):
            if order == "pct_first":
                _add(match.group(2), match.group(1))
            else:
                _add(match.group(1), match.group(2))

    return discounts


def parse_reddit_bonuses(text):
    """Extract 2X/3X bonus events from Reddit post text.

    Handles two common formats:
    1. Inline: "2X GTA$ & RP on Clubhouse Contracts"
    2. Header + sub-items:
           2X GTA$ and RP:
           - Clubhouse Contracts
           - MC Work and Challenges

    Returns:
        List of bonus description strings.
    """
    bonuses = []
    seen = set()

    mult_map = {"double": "2X", "triple": "3X", "quadruple": "4X"}

    # Reward-type strings that are NOT activity names
    _reward_junk_re = re.compile(
        r"^(?:GTA\$?\s*(?:and|&)\s*RP|GTA\$|RP|Rewards?|payouts?)$",
        re.IGNORECASE,
    )

    def _normalise_mult(mult):
        ml = mult.lower().strip()
        if ml in mult_map:
            return mult_map[ml]
        if ml[0].isdigit():
            return ml[0] + "X"
        return mult

    def _add(mult, activity):
        mult = _normalise_mult(mult)

        activity = activity.strip().rstrip(".,;:–—-*()").strip()
        # Strip leading bullets/whitespace
        activity = re.sub(r"^[-•*>\s]+", "", activity).strip()
        # Strip "GTA$ & RP on " prefix if the pattern over-captured
        activity = re.sub(
            r"^GTA\$?\s*(?:and|&)\s*RP\s+(?:on|in|from|for)\s+",
            "", activity, flags=re.IGNORECASE,
        ).strip()
        # Strip parenthetical membership notes
        activity = re.sub(r"\s*\(\d+[Xx]\s+for\s+GTA\+.*$", "", activity).strip()
        if not activity or len(activity) < 3:
            return
        # Skip if activity is just a reward type, not a real activity
        if _reward_junk_re.match(activity):
            return
        # Skip if the "activity" starts with another multiplier (double-match)
        if re.match(r"^\d[Xx]\s+", activity):
            return

        key = activity.lower()
        if key not in seen:
            seen.add(key)
            bonuses.append(f"{mult} on {activity}")

    # ---------------------------------------------------------------
    # Pass 1: Header + sub-items format
    # Lines like "2X GTA$ and RP:" followed by "- Activity" lines
    # ---------------------------------------------------------------
    lines = text.splitlines()
    header_re = re.compile(
        r"^(\d)[Xx]\s+(?:GTA\$?\s*(?:and|&)\s*RP|Rewards?|GTA\$?|RP)\s*"
        r"(?:[:–—\-]\s*)?$",
        re.IGNORECASE,
    )
    subitem_re = re.compile(r"^\s*[-•*>]\s+(.+)$")

    i = 0
    while i < len(lines):
        hm = header_re.match(lines[i].strip())
        if hm:
            mult = hm.group(1)
            # Collect sub-items from following lines
            j = i + 1
            while j < len(lines):
                sm = subitem_re.match(lines[j])
                if sm:
                    _add(mult, sm.group(1))
                    j += 1
                elif not lines[j].strip():
                    j += 1  # skip blank lines
                else:
                    break
            i = j
        else:
            i += 1

    # ---------------------------------------------------------------
    # Pass 2: Inline patterns (only adds items not already seen)
    # ---------------------------------------------------------------
    inline_patterns = [
        # "2X GTA$ & RP on Counterfeit Cash"
        (re.compile(
            r"(\d)[Xx]\s+(?:GTA\$?\s*(?:and|&)\s*RP|Rewards?|GTA\$?|RP)"
            r"\s+(?:on|in|from|for)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "mult_first"),
        # "Double/Triple Rewards on Counterfeit Cash"
        (re.compile(
            r"(Double|Triple|Quadruple)\s+(?:GTA\$?\s*(?:and|&)\s*RP|Rewards?|payouts?)"
            r"\s+(?:on|in|from|for)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "mult_first"),
        # "2X on Counterfeit Cash"
        (re.compile(
            r"(\d)[Xx]\s+(?:on|in|from)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "mult_first"),
        # "3x Lunar New Year Stunt Races" (no preposition)
        (re.compile(
            r"(\d)[Xx]\s+([A-Z][^,\n]{3,}?)(?:\s*[\|,\n(]|$)",
            re.MULTILINE,
        ), "mult_first"),
        # "Double on Counterfeit Cash"
        (re.compile(
            r"(Double|Triple|Quadruple)\s+(?:on|in|from|for)\s+(.+?)(?:\s*[\|,\n]|$)",
            re.IGNORECASE | re.MULTILINE,
        ), "mult_first"),
        # "Counterfeit Cash (2X)" or "Counterfeit Cash — 2X"
        (re.compile(
            r"[-•*>]?\s*(.+?)\s*(?:\(|[–—\-]+\s*)(\d[Xx]|Double|Triple)\)?",
            re.IGNORECASE,
        ), "activity_first"),
    ]

    for pattern, order in inline_patterns:
        for match in pattern.finditer(text):
            if order == "mult_first":
                _add(match.group(1), match.group(2))
            else:
                _add(match.group(2), match.group(1))

    return bonuses


def parse_reddit_podium(text):
    """Extract the podium/prize ride vehicle from Reddit post text.

    After markdown stripping, lines look like:
        Podium Vehicle: Karin Sultan RS Classic
        Prize Ride: Grotti Stinger GT
        Prize Ride Challenge: Place Top 4 in the LS Car Meet Series

    Returns:
        Dict with 'podium_vehicle', 'prize_ride', and 'test_track' keys.
    """
    result = {"podium_vehicle": None, "prize_ride": None, "test_track": None}

    # Work line-by-line for reliable extraction
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        line_lower = line.lower()

        # Podium Vehicle / Lucky Wheel
        if result["podium_vehicle"] is None:
            for trigger in ["podium vehicle:", "lucky wheel:"]:
                if trigger in line_lower:
                    # Extract everything after the trigger
                    idx = line_lower.index(trigger) + len(trigger)
                    vehicle = line[idx:].strip().rstrip(".,;:–—-*").strip()
                    if vehicle and len(vehicle) > 2:
                        result["podium_vehicle"] = vehicle
                    break

        # Prize Ride — match "Prize Ride:", "Prize Ride Vehicle:", etc.
        # but NOT "Prize Ride Challenge:"
        if result["prize_ride"] is None:
            pr_match = re.search(
                r"Prize\s+Ride(?:\s+Vehicle)?\s*:\s*(.+?)$",
                line, re.IGNORECASE,
            )
            if pr_match:
                vehicle = pr_match.group(1).strip().rstrip(".,;:–—-*").strip()
                if vehicle and len(vehicle) > 2:
                    result["prize_ride"] = vehicle

        # Test Track
        if result["test_track"] is None:
            if "test track:" in line_lower:
                idx = line_lower.index("test track:") + len("test track:")
                vehicle = line[idx:].strip().rstrip(".,;:–—-*").strip()
                if vehicle and len(vehicle) > 2:
                    result["test_track"] = vehicle

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
    raw_text = post["selftext"]
    title = post.get("title", "")

    # Strip markdown formatting so regex patterns match clean text
    text = _strip_markdown(raw_text)

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
        "raw_text": raw_text,
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

    # Step 4: Show cleaned text preview
    cleaned = _strip_markdown(best["selftext"])
    print(f"\n[Step 4] Cleaned text preview ({len(cleaned)} chars):")
    for line in cleaned.splitlines()[:40]:
        line = line.strip()
        if line:
            print(f"  | {line}")

    print("\n" + "=" * 60)
    print("  Reddit scraper test complete.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_reddit_scraper()
