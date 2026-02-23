"""Visual comparison tables for GTA Online items, heists, and businesses.

Generates ASCII tables (terminal/markdown/CSV) and bar charts for
comparing discounts, heist efficiency, business income, and savings.
"""

import csv
import io
import json
import os
import re

from src.prices import load_prices
from src.roi_calculator import (
    INCOME_RATES,
    calculate_business_roi,
    calculate_discount_savings,
    calculate_heist_roi,
)


# ---------------------------------------------------------------------------
# Helper: currency formatting
# ---------------------------------------------------------------------------


def format_currency(amount):
    """Format an integer as a dollar string.

    Args:
        amount: Numeric value (int or float).

    Returns:
        Formatted string, e.g. ``"$1,234,567"``.
    """
    if amount is None:
        return "$0"
    return f"${int(amount):,}"


# ---------------------------------------------------------------------------
# Internal table rendering
# ---------------------------------------------------------------------------

_EFFORT_MAP = {
    "passive": "Low",
    "semi-passive": "Medium",
    "active": "High",
}


def _col_widths(headers, rows):
    """Calculate column widths from headers and row data."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    return widths


def _render_terminal(headers, rows, widths):
    """Render a box-drawing ASCII table."""
    lines = []

    def _hr(left, mid, right, fill="─"):
        segs = [fill * (w + 2) for w in widths]
        return left + mid.join(segs) + right

    def _row(cells):
        parts = []
        for cell, w in zip(cells, widths):
            parts.append(f" {str(cell).ljust(w)} ")
        return "│" + "│".join(parts) + "│"

    lines.append(_hr("┌", "┬", "┐"))
    lines.append(_row(headers))
    lines.append(_hr("├", "┼", "┤"))
    for row in rows:
        lines.append(_row(row))
    lines.append(_hr("└", "┴", "┘"))

    return "\n".join(lines)


def _render_markdown(headers, rows, widths):
    """Render a GitHub-flavoured markdown table."""
    lines = []

    def _row(cells):
        parts = [f" {str(c).ljust(w)} " for c, w in zip(cells, widths)]
        return "|" + "|".join(parts) + "|"

    lines.append(_row(headers))
    lines.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for row in rows:
        lines.append(_row(row))

    return "\n".join(lines)


def _render_csv(headers, rows):
    """Render CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def _render_table(headers, rows, fmt="terminal"):
    """Dispatch to the correct renderer."""
    widths = _col_widths(headers, rows)
    if fmt == "markdown":
        return _render_markdown(headers, rows, widths)
    if fmt == "csv":
        return _render_csv(headers, rows)
    return _render_terminal(headers, rows, widths)


# ---------------------------------------------------------------------------
# 1. General comparison table
# ---------------------------------------------------------------------------


def generate_comparison_table(items, prices_db=None, format="terminal"):
    """Generate a comparison table for discounted items.

    Items not found in the price database are still included with
    ``"--"`` placeholders so the user sees everything from the weekly
    update at a glance.

    Args:
        items: List of dicts with ``"item"`` and ``"discount"`` keys.
        prices_db: Optional pre-loaded prices dict.
        format: ``"terminal"``, ``"markdown"``, or ``"csv"``.

    Returns:
        Formatted table string.
    """
    if prices_db is None:
        prices_db = load_prices()

    headers = ["Item", "Base Price", "Discount", "Sale Price", "ROI (30d)"]
    rows = []

    for entry in items:
        name = entry.get("item", "")
        disc_pct = entry.get("discount", 0)

        savings = calculate_discount_savings(name, disc_pct, prices_db)

        if savings:
            # Determine ROI label
            biz = calculate_business_roi(savings["item"], prices_db)
            heist = _heist_for_item(savings["item"], prices_db)
            if heist:
                roi_label = heist["roi_30_days"]
            elif biz:
                roi_label = biz["roi_30_days"]
            else:
                roi_label = "N/A"

            rows.append([
                savings["item"],
                format_currency(savings["base_price"]),
                f"{int(disc_pct)}%",
                format_currency(savings["best_price"]),
                roi_label,
            ])
        else:
            # Item not in price DB — still show it with placeholders
            rows.append([
                name,
                "--",
                f"{int(disc_pct)}%",
                "--",
                "--",
            ])

    if not rows:
        return "No discounts to display."

    return _render_table(headers, rows, fmt=format)


# ---------------------------------------------------------------------------
# 2. Heist comparison table
# ---------------------------------------------------------------------------


def generate_heist_comparison(heists=None, prices_db=None, format="terminal"):
    """Compare heist efficiency side-by-side.

    Args:
        heists: Optional list of heist name strings to include.
            Defaults to all heists in the database.
        prices_db: Optional pre-loaded prices dict.
        format: ``"terminal"``, ``"markdown"``, or ``"csv"``.

    Returns:
        Formatted table string.
    """
    if prices_db is None:
        prices_db = load_prices()

    if heists is None:
        heists = list(prices_db.get("heists", {}).keys())

    headers = ["Heist", "Setup Cost", "Avg Payout", "Time (min)", "$/Hour"]
    rows = []

    for h_name in heists:
        roi = calculate_heist_roi(h_name, prices_db=prices_db)
        if not roi:
            continue

        rows.append([
            roi["heist"],
            format_currency(roi["total_investment"]),
            format_currency(roi["avg_payout_per_run"]),
            str(roi["avg_time_per_run_minutes"]),
            format_currency(roi["hourly_rate"]),
        ])

    return _render_table(headers, rows, fmt=format)


# ---------------------------------------------------------------------------
# 3. Business comparison table
# ---------------------------------------------------------------------------


def generate_business_comparison(businesses=None, prices_db=None,
                                 time_period_days=30, hours_per_day=3,
                                 format="terminal"):
    """Compare passive/semi-passive income businesses.

    Args:
        businesses: Optional list of business name strings.
            Defaults to all businesses with known income rates.
        prices_db: Optional pre-loaded prices dict.
        time_period_days: Analysis period in days (default 30).
        hours_per_day: Assumed play hours per day (default 3).
        format: ``"terminal"``, ``"markdown"``, or ``"csv"``.

    Returns:
        Formatted table string.
    """
    if prices_db is None:
        prices_db = load_prices()

    if businesses is None:
        businesses = list(INCOME_RATES.keys())

    total_hours = hours_per_day * time_period_days
    hours_per_week = hours_per_day * 7

    headers = [
        "Business",
        "Setup Cost",
        f"{time_period_days}d Profit",
        "Break-even",
        "Effort",
    ]
    rows = []

    for biz_name in businesses:
        roi = calculate_business_roi(biz_name, prices_db,
                                     hours_per_week=hours_per_week)
        if not roi:
            continue

        period_profit = roi["avg_hourly_profit"] * total_hours
        break_even_days = round(roi["break_even_hours"] / hours_per_day)
        effort = _EFFORT_MAP.get(roi["income_type"], "Unknown")

        rows.append([
            roi["item"],
            format_currency(roi["base_price"]),
            format_currency(period_profit),
            f"{break_even_days} days",
            effort,
        ])

    return _render_table(headers, rows, fmt=format)


# ---------------------------------------------------------------------------
# 4. Discount savings bar chart
# ---------------------------------------------------------------------------


def generate_discount_chart(all_discounts, prices_db=None, top_n=10,
                            bar_width=40):
    """Generate an ASCII bar chart of top savings.

    When dollar-amount savings are available (item found in price DB),
    the chart is sorted by absolute savings.  When no items have known
    prices, the chart falls back to ranking by discount percentage so
    that the user still gets a useful visual.

    Args:
        all_discounts: List of dicts with ``"item"`` and ``"discount"`` keys.
        prices_db: Optional pre-loaded prices dict.
        top_n: Number of items to show (default 10).
        bar_width: Maximum bar length in characters (default 40).

    Returns:
        Formatted ASCII bar chart string.
    """
    if prices_db is None:
        prices_db = load_prices()

    if not all_discounts:
        return "No discount data available."

    priced = []
    unpriced = []

    for entry in all_discounts:
        name = entry.get("item", "")
        disc_pct = int(entry.get("discount", 0))

        result = calculate_discount_savings(name, disc_pct, prices_db)
        if result:
            priced.append({
                "item": result["item"],
                "savings": result["savings_vs_base"],
                "discount_percent": disc_pct,
            })
        else:
            unpriced.append({
                "item": name,
                "savings": 0,
                "discount_percent": disc_pct,
            })

    # Prefer dollar-savings ranking; fall back to discount-% ranking
    if priced:
        chart_items = sorted(priced, key=lambda x: x["savings"], reverse=True)
        # Append unpriced items at the end so they're still visible
        chart_items.extend(
            sorted(unpriced, key=lambda x: x["discount_percent"], reverse=True)
        )
        use_dollars = True
    else:
        chart_items = sorted(unpriced, key=lambda x: x["discount_percent"], reverse=True)
        use_dollars = False

    chart_items = chart_items[:top_n]

    if not chart_items:
        return "No discount data available."

    max_name_len = max(len(s["item"]) for s in chart_items)
    count = min(top_n, len(chart_items))

    lines = [f"Top {count} Savings This Week:", ""]

    if use_dollars:
        max_savings = chart_items[0]["savings"] if chart_items[0]["savings"] else 1
        max_val_len = max(
            len(format_currency(s["savings"])) if s["savings"] else 3
            for s in chart_items
        )
        for s in chart_items:
            name_padded = s["item"].ljust(max_name_len)
            if s["savings"]:
                bar_len = int((s["savings"] / max_savings) * bar_width)
                val_padded = format_currency(s["savings"]).ljust(max_val_len)
            else:
                bar_len = 1  # minimal bar for unpriced items
                val_padded = "--".ljust(max_val_len)
            bar = "\u2588" * max(bar_len, 0)
            lines.append(
                f"  {name_padded}  {val_padded} {bar} ({s['discount_percent']}% off)"
            )
    else:
        # No dollar data — chart by discount percentage
        max_pct = chart_items[0]["discount_percent"] if chart_items else 1
        for s in chart_items:
            bar_len = int((s["discount_percent"] / max_pct) * bar_width) if max_pct else 0
            bar = "\u2588" * max(bar_len, 1)
            name_padded = s["item"].ljust(max_name_len)
            lines.append(
                f"  {name_padded}  {bar} ({s['discount_percent']}% off)"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Export comparison data
# ---------------------------------------------------------------------------


def export_comparison(comparison_data, filename, format="csv"):
    """Export comparison data to a file for external analysis.

    Saves to ``data/comparisons/<filename>``.

    Args:
        comparison_data: Either a list of row-dicts, or a pre-rendered
            table string (for CSV pass-through).
        filename: Output filename (extension added if missing).
        format: ``"csv"`` or ``"json"``.

    Returns:
        Absolute path to the created file.
    """
    out_dir = os.path.join("data", "comparisons")
    os.makedirs(out_dir, exist_ok=True)

    # Ensure correct extension
    if format == "csv" and not filename.endswith(".csv"):
        filename += ".csv"
    elif format == "json" and not filename.endswith(".json"):
        filename += ".json"

    path = os.path.join(out_dir, filename)

    if format == "json":
        with open(path, "w") as f:
            json.dump(comparison_data, f, indent=2)
    elif format == "csv":
        if isinstance(comparison_data, str):
            # Already rendered CSV text
            with open(path, "w", newline="") as f:
                f.write(comparison_data)
        elif isinstance(comparison_data, list) and comparison_data:
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=comparison_data[0].keys())
                writer.writeheader()
                writer.writerows(comparison_data)
        else:
            with open(path, "w") as f:
                f.write("")

    return os.path.abspath(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _heist_for_item(item_name, prices_db):
    """Check if an item is a heist requirement and return its ROI."""
    norm = _norm(item_name)
    for hname, hinfo in prices_db.get("heists", {}).items():
        for req in hinfo.get("requirements", []):
            if _norm(req) == norm or norm in _norm(req):
                return calculate_heist_roi(hname, prices_db=prices_db)
    return None


def _norm(name):
    """Lowercase normalised name for matching."""
    lower = name.lower().strip()
    return re.sub(r"[^a-z0-9\s]", "", lower).strip()
