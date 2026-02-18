# GTA Newswire Tracker

Track GTA Online weekly updates from the Rockstar Newswire. Get a digest of discounts, events, bonuses, and podium vehicles, and check them against your personal wishlist.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

### Check the latest weekly update

```bash
python main.py check
```

### Manage your wishlist

```bash
# Add an item
python main.py wishlist add "Toreador" -c vehicles

# Remove an item
python main.py wishlist remove "Toreador" -c vehicles

# List all wishlist items
python main.py wishlist list
```

## Project Structure

```
gta-newswire-tracker/
├── src/
│   ├── __init__.py
│   ├── scraper.py          # Newswire scraping logic
│   ├── parser.py           # Extract discounts, events, podium vehicle
│   ├── wishlist.py         # Wishlist management
│   └── digest.py           # Format and display digest
├── data/
│   └── wishlist.json       # User's wishlist storage
├── config.py               # Configuration (URLs, settings)
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
└── README.md
```
