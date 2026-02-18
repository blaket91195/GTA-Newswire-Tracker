"""Newswire scraping logic for fetching GTA Online weekly updates."""

import requests
from bs4 import BeautifulSoup

import config


def fetch_newswire_page(url=None):
    """Fetch the Rockstar Newswire page HTML.

    Args:
        url: URL to fetch. Defaults to the GTA Online newswire URL.

    Returns:
        BeautifulSoup object of the parsed page, or None on failure.
    """
    target_url = url or config.NEWSWIRE_GTA_ONLINE_URL
    try:
        response = requests.get(
            target_url,
            headers=config.REQUEST_HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        print(f"Error fetching newswire: {e}")
        return None


def fetch_article(url):
    """Fetch a single newswire article page.

    Args:
        url: Full URL to the article.

    Returns:
        BeautifulSoup object of the parsed article, or None on failure.
    """
    try:
        response = requests.get(
            url,
            headers=config.REQUEST_HEADERS,
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        print(f"Error fetching article: {e}")
        return None


def get_latest_articles(soup):
    """Extract article links and titles from the newswire listing page.

    Args:
        soup: BeautifulSoup object of the newswire listing page.

    Returns:
        List of dicts with 'title', 'url', and 'date' keys.
    """
    articles = []
    if soup is None:
        return articles

    # Look for article containers on the newswire page
    article_elements = soup.select("a[href*='/newswire/article/']")
    seen_urls = set()

    for element in article_elements:
        href = element.get("href", "")
        if href in seen_urls:
            continue
        seen_urls.add(href)

        title = element.get_text(strip=True)
        if not title:
            continue

        url = href
        if not url.startswith("http"):
            url = f"https://www.rockstargames.com{href}"

        articles.append({
            "title": title,
            "url": url,
            "date": None,
        })

    return articles
