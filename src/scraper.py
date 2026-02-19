"""GraphQL API scraper for fetching GTA Online newswire articles.

Uses the Rockstar Games GraphQL endpoint to retrieve articles from the
Newswire, including weekly update posts with discounts, bonuses, and events.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL API constants
# ---------------------------------------------------------------------------

GRAPHQL_BASE_URL = "https://graph.rockstargames.com/"

PERSISTED_QUERY_HASH = (
    "aef12205cdcce5be34d9a2aa5e118635df895336ea5ea87e73b6b5d8a18ccc1a"
)

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Origin": "https://www.rockstargames.com",
    "Referer": "https://www.rockstargames.com/",
}

ROCKSTAR_BASE = "https://www.rockstargames.com"

# Tag IDs
TAG_GTA_ONLINE = 702
TAG_RED_DEAD_ONLINE = 736
TAG_ALL = 0

# Weekly-update detection keywords (matched case-insensitively)
WEEKLY_KEYWORDS = ["this week", "bonuses", "discounts", "triple", "double"]

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------


def build_newswire_url(tag_id=TAG_GTA_ONLINE, page=1, limit=20):
    """Build the GraphQL API URL for fetching newswire articles.

    Args:
        tag_id: 702 for GTA Online, 736 for Red Dead Online, 0 for all.
        page: Page number (starts at 1).
        limit: Articles per page (default 20).

    Returns:
        Full API URL with encoded query parameters.
    """
    variables = {
        "tagId": tag_id,
        "page": page,
        "metaUrl": "/newswire",
        "limit": limit,
        "locale": "en_us",
    }

    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": PERSISTED_QUERY_HASH,
        }
    }

    params = {
        "origin": "https://www.rockstargames.com",
        "operationName": "NewswireList",
        "variables": json.dumps(variables),
        "extensions": json.dumps(extensions),
    }

    return GRAPHQL_BASE_URL + "?" + urlencode(params)


# ---------------------------------------------------------------------------
# Core API request with retry logic
# ---------------------------------------------------------------------------


def _request_with_retry(url, max_retries=MAX_RETRIES):
    """Make a GET request with exponential-backoff retry.

    Args:
        url: The URL to fetch.
        max_retries: Maximum number of attempts.

    Returns:
        Parsed JSON dict on success.

    Raises:
        RuntimeError: If all retries are exhausted or an unrecoverable error
            occurs (e.g. persisted-query hash mismatch).
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        logger.info("API request (attempt %d/%d): %s", attempt, max_retries, url)

        try:
            response = requests.get(
                url,
                headers=API_HEADERS,
                timeout=config.REQUEST_TIMEOUT,
            )
            logger.info("Response status: %d", response.status_code)
            response.raise_for_status()
        except requests.Timeout as exc:
            last_error = exc
            logger.warning("Request timed out (attempt %d/%d)", attempt, max_retries)
            if attempt < max_retries:
                _backoff(attempt)
            continue
        except requests.ConnectionError as exc:
            last_error = exc
            logger.warning("Connection error (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                _backoff(attempt)
            continue
        except requests.HTTPError as exc:
            last_error = exc
            status = response.status_code
            logger.error("HTTP %d error on attempt %d/%d", status, attempt, max_retries)
            # Don't retry client errors other than 429
            if 400 <= status < 500 and status != 429:
                raise RuntimeError(
                    f"HTTP {status} error from Rockstar API. "
                    "The API may have changed — check the persisted-query hash."
                ) from exc
            if attempt < max_retries:
                _backoff(attempt)
            continue

        # Parse JSON
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Failed to parse JSON from Rockstar API response."
            ) from exc

        # Check for GraphQL-level errors
        if data.get("errors"):
            error_msgs = [e.get("message", str(e)) for e in data["errors"]]
            joined = "; ".join(error_msgs)
            if "PersistedQueryNotFound" in joined:
                raise RuntimeError(
                    "Persisted query hash rejected by API. The hash "
                    f"'{PERSISTED_QUERY_HASH}' may be outdated — Rockstar "
                    "may have updated their API. Check for a new hash."
                )
            raise RuntimeError(f"GraphQL API returned errors: {joined}")

        return data

    raise RuntimeError(
        f"All {max_retries} API request attempts failed. Last error: {last_error}"
    )


def _backoff(attempt):
    """Sleep with exponential backoff."""
    delay = RETRY_BACKOFF_BASE ** attempt
    logger.info("Retrying in %d seconds...", delay)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Debug cache
# ---------------------------------------------------------------------------


def _save_debug_cache(data, tag_id, page):
    """Save raw JSON response to data/cache/ for debugging.

    Only writes when the DEBUG_CACHE config flag is enabled.
    """
    if not getattr(config, "DEBUG_CACHE", False):
        return

    cache_dir = os.path.join("data", "cache")
    os.makedirs(cache_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"newswire_tag{tag_id}_p{page}_{timestamp}.json"
    filepath = os.path.join(cache_dir, filename)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    logger.debug("Saved debug cache: %s", filepath)


# ---------------------------------------------------------------------------
# Article parsing helpers
# ---------------------------------------------------------------------------


def _parse_article(raw):
    """Normalise a single article dict from the API response.

    Args:
        raw: A single item from ``data.posts.results``.

    Returns:
        Dict with normalised keys.
    """
    url = raw.get("url", "")
    if url and not url.startswith("http"):
        url = ROCKSTAR_BASE + url

    # Extract the best available image
    image_url = None
    preview = raw.get("preview_images_parsed") or {}
    block = preview.get("newswire_block") or {}
    image_url = block.get("d16x9") or block.get("square")

    # Capture body/blurb/subtitle if the API returns them — the
    # persisted query may or may not include these fields.
    blurb = (
        raw.get("body")
        or raw.get("blurb")
        or raw.get("content")
        or raw.get("subtitle")
        or raw.get("summary")
        or ""
    )

    return {
        "id": raw.get("id"),
        "url": url,
        "title": raw.get("title", ""),
        "date": raw.get("created_formatted", ""),
        "image_url": image_url,
        "blurb": blurb,
        "tags": [
            t.get("name", "") for t in (raw.get("primary_tags") or [])
        ],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_newswire_articles(tag_id=TAG_GTA_ONLINE, page=1):
    """Fetch a page of newswire articles from the Rockstar GraphQL API.

    Args:
        tag_id: Tag filter (702 = GTA Online, 736 = RDO, 0 = all).
        page: Page number (1-indexed).

    Returns:
        Dict with ``"articles"`` (list) and ``"paging"`` (dict) keys,
        or None on failure.
    """
    url = build_newswire_url(tag_id=tag_id, page=page)

    try:
        data = _request_with_retry(url)
    except RuntimeError as exc:
        logger.error("Failed to fetch newswire articles: %s", exc)
        return None

    _save_debug_cache(data, tag_id, page)

    posts = (data.get("data") or {}).get("posts") or {}
    raw_results = posts.get("results") or []
    paging = posts.get("paging") or {}

    articles = [_parse_article(r) for r in raw_results]

    logger.info(
        "Fetched %d articles (page %d/%s)",
        len(articles),
        paging.get("page", page),
        paging.get("pageCount", "?"),
    )

    return {
        "articles": articles,
        "paging": paging,
    }


def get_latest_weekly_update():
    """Find the most recent GTA Online weekly-update article.

    Fetches the first page of GTA Online articles and looks for one whose
    title contains weekly-update keywords (e.g. "this week", "bonuses",
    "discounts").  Prefers articles posted on a Thursday or within the
    last 7 days.

    Returns:
        Dict with article info, or None if no matching article is found.
    """
    result = fetch_newswire_articles(tag_id=TAG_GTA_ONLINE, page=1)
    if result is None:
        return None

    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)
    candidates = []

    for article in result["articles"]:
        title_lower = article["title"].lower()
        if not any(kw in title_lower for kw in WEEKLY_KEYWORDS):
            continue

        # Try to parse the date
        parsed_date = None
        if article["date"]:
            try:
                parsed_date = dateutil_parser.parse(article["date"])
            except (ValueError, OverflowError):
                pass

        # Score the article: prefer Thursday + recent
        score = 0
        if parsed_date:
            if parsed_date >= seven_days_ago:
                score += 10
            if parsed_date.weekday() == 3:  # Thursday
                score += 5

        candidates.append((score, parsed_date, article))

    if not candidates:
        logger.warning("No weekly-update article found in the latest results.")
        return None

    # Sort by score descending, then by date descending
    candidates.sort(
        key=lambda c: (c[0], c[1] or datetime.min),
        reverse=True,
    )

    best = candidates[0][2]
    logger.info("Latest weekly update: %s", best["title"])
    return best


def get_full_article_list(tag_id=TAG_GTA_ONLINE, max_pages=3):
    """Fetch multiple pages of newswire articles.

    Respects the API's ``paging.nextPage`` flag and pauses 1 second
    between requests to be polite.

    Args:
        tag_id: Tag filter (702 = GTA Online, 736 = RDO, 0 = all).
        max_pages: Maximum number of pages to fetch.

    Returns:
        List of article dicts across all fetched pages.
    """
    all_articles = []

    for page_num in range(1, max_pages + 1):
        logger.info("Fetching page %d/%d...", page_num, max_pages)
        result = fetch_newswire_articles(tag_id=tag_id, page=page_num)

        if result is None:
            logger.error("Failed on page %d — stopping pagination.", page_num)
            break

        all_articles.extend(result["articles"])

        # Check if there are more pages
        if not result["paging"].get("nextPage", False):
            logger.info("No more pages available.")
            break

        # Be polite between requests
        if page_num < max_pages:
            time.sleep(1)

    logger.info("Total articles fetched: %d", len(all_articles))
    return all_articles


# ---------------------------------------------------------------------------
# Test / demo
# ---------------------------------------------------------------------------


def test_scraper():
    """Run a quick integration test against the live API.

    - Fetches the latest GTA Online articles
    - Prints the first 5 article titles and dates
    - Verifies image URLs are present
    - Tests pagination by fetching 2 pages
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("  GTA Newswire Tracker — Scraper Test")
    print("=" * 60)

    # --- Test 1: Fetch single page ---
    print("\n[Test 1] Fetching first page of GTA Online articles...")
    result = fetch_newswire_articles(tag_id=TAG_GTA_ONLINE, page=1)

    if result is None:
        print("  FAIL: Could not fetch articles.")
        return False

    articles = result["articles"]
    paging = result["paging"]
    print(f"  OK: Got {len(articles)} articles "
          f"(page {paging.get('page')}/{paging.get('pageCount')})")

    # --- Test 2: Print first 5 ---
    print("\n[Test 2] First 5 articles:")
    for i, art in enumerate(articles[:5], 1):
        has_img = "yes" if art["image_url"] else "NO"
        print(f"  {i}. [{art['date']}] {art['title']}")
        print(f"     URL: {art['url']}")
        print(f"     Image: {has_img}")

    # --- Test 3: Verify images ---
    print("\n[Test 3] Image URL check:")
    with_images = sum(1 for a in articles if a["image_url"])
    print(f"  {with_images}/{len(articles)} articles have image URLs")

    # --- Test 4: Weekly update detection ---
    print("\n[Test 4] Finding latest weekly update...")
    weekly = get_latest_weekly_update()
    if weekly:
        print(f"  Found: {weekly['title']}")
        print(f"  Date:  {weekly['date']}")
        print(f"  URL:   {weekly['url']}")
    else:
        print("  No weekly update article found (may be between weeks)")

    # --- Test 5: Pagination ---
    print("\n[Test 5] Testing pagination (2 pages)...")
    all_articles = get_full_article_list(tag_id=TAG_GTA_ONLINE, max_pages=2)
    print(f"  OK: Got {len(all_articles)} total articles across pages")

    print("\n" + "=" * 60)
    print("  All tests complete.")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_scraper()
