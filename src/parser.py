"""Extract discounts, events, and podium vehicle from newswire articles."""

import re

import config


def extract_discounts(text):
    """Extract discount information from article text.

    Args:
        text: Article body text.

    Returns:
        List of discount strings found in the text.
    """
    discounts = []
    lines = text.split("\n")

    for line in lines:
        line_lower = line.strip().lower()
        if any(keyword in line_lower for keyword in config.DISCOUNT_KEYWORDS):
            cleaned = line.strip()
            if cleaned and len(cleaned) > 5:
                discounts.append(cleaned)

    return discounts


def extract_events(text):
    """Extract event/bonus information from article text.

    Args:
        text: Article body text.

    Returns:
        List of event strings found in the text.
    """
    events = []
    lines = text.split("\n")

    for line in lines:
        line_lower = line.strip().lower()
        if any(keyword in line_lower for keyword in config.EVENT_KEYWORDS):
            cleaned = line.strip()
            if cleaned and len(cleaned) > 5:
                events.append(cleaned)

    return events


def extract_podium_vehicle(text):
    """Extract the podium/prize ride vehicle from article text.

    Args:
        text: Article body text.

    Returns:
        Vehicle name string, or None if not found.
    """
    for keyword in config.PODIUM_KEYWORDS:
        pattern = rf"{re.escape(keyword)}[:\s\-–—]+(.+?)(?:\.|,|\n|$)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            vehicle = match.group(1).strip()
            if vehicle:
                return vehicle

    return None


def parse_article(soup):
    """Parse a full article page and extract all relevant info.

    Args:
        soup: BeautifulSoup object of the article page.

    Returns:
        Dict with 'discounts', 'events', and 'podium_vehicle' keys.
    """
    result = {
        "discounts": [],
        "events": [],
        "podium_vehicle": None,
    }

    if soup is None:
        return result

    # Extract article body text
    body = soup.select_one("article") or soup.select_one(".article-body") or soup
    text = body.get_text(separator="\n", strip=True)

    result["discounts"] = extract_discounts(text)
    result["events"] = extract_events(text)
    result["podium_vehicle"] = extract_podium_vehicle(text)

    return result
