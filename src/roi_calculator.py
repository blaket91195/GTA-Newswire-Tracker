"""ROI analysis for GTA Online purchases and investments.

Calculates discount savings, business break-even times, heist ROI,
and generates purchase recommendations based on budget and playstyle.
"""

import re

from src.prices import get_item_price, load_prices


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hourly income rates for businesses/properties
INCOME_RATES = {
    "Nightclub": {
        "hourly": 50000,
        "type": "passive",
        "notes": "Passive income with Technicians assigned",
    },
    "Bunker": {
        "hourly": 60000,
        "type": "semi-passive",
        "notes": "Requires supply purchases or steal missions",
    },
    "Agency": {
        "hourly": 85000,
        "type": "active",
        "notes": "Security Contracts and Payphone Hits",
    },
    "Auto Shop": {
        "hourly": 75000,
        "type": "active",
        "notes": "Contract missions and customer deliveries",
    },
    "Acid Lab": {
        "hourly": 55000,
        "type": "semi-passive",
        "notes": "Produces product over time; sell missions required",
    },
    "Vehicle Warehouse": {
        "hourly": 80000,
        "type": "active",
        "notes": "Import/Export high-end vehicle sourcing",
    },
    "Special Cargo Warehouse": {
        "hourly": 70000,
        "type": "active",
        "notes": "Buy low, fill warehouse, sell high",
    },
    "Arcade": {
        "hourly": 5000,
        "type": "passive",
        "notes": "Minimal passive income from arcade machines",
    },
    "Cocaine Lockup": {
        "hourly": 74000,
        "type": "semi-passive",
        "notes": "Most profitable MC business when fully upgraded",
    },
    "Methamphetamine Lab": {
        "hourly": 51000,
        "type": "semi-passive",
        "notes": "Second most profitable MC business when fully upgraded",
    },
    "Counterfeit Cash Factory": {
        "hourly": 48000,
        "type": "semi-passive",
        "notes": "Third best MC business when fully upgraded",
    },
    "Salvage Yard": {
        "hourly": 40000,
        "type": "active",
        "notes": "Chop Shop robbery missions and vehicle salvaging",
    },
}

# Playstyle priorities — ordered lists of recommended items
PLAYSTYLE_PRIORITIES = {
    "solo": [
        "Kosatka", "Sparrow Helicopter", "Agency", "Auto Shop",
        "Acid Lab", "Nightclub", "Bunker", "Oppressor Mk II",
    ],
    "crew": [
        "Arcade", "Kosatka", "Nightclub", "Bunker",
        "Agency", "Terrorbyte", "Oppressor Mk II",
    ],
    "grinder": [
        "Nightclub", "Bunker", "Acid Lab", "Kosatka",
        "Vehicle Warehouse", "Special Cargo Warehouse", "Agency",
    ],
    "casual": [
        "Auto Shop", "Agency", "Nightclub", "Kosatka",
        "Buzzard Attack Chopper",
    ],
    "mixed": [
        "Kosatka", "Nightclub", "Agency", "Sparrow Helicopter",
        "Bunker", "Auto Shop", "Oppressor Mk II",
    ],
}

# Items that primarily enable other content rather than earn directly
_ENABLER_ITEMS = {
    "Kosatka": "Enables highest-paying solo heist",
    "Sparrow Helicopter": "Essential Kosatka upgrade, saves prep time",
    "Arcade": "Required for Diamond Casino Heist",
    "Terrorbyte": "Unlocks Oppressor Mk II upgrades and Client Jobs",
    "Buzzard Attack Chopper": "Free CEO vehicle after purchase, huge time saver",
    "Oppressor Mk II": "Fastest grinding vehicle with missiles",
}


# ---------------------------------------------------------------------------
# 1. Discount savings
# ---------------------------------------------------------------------------


def calculate_discount_savings(item_name, discount_percent, prices_db=None):
    """Calculate savings from a discount on a specific item.

    Args:
        item_name: Item name (fuzzy matched against price database).
        discount_percent: Discount percentage (e.g. 40 for 40% off).
        prices_db: Optional pre-loaded prices dict. Loaded if None.

    Returns:
        Dict with price breakdown and best deal info, or None if item
        not found in the price database.
    """
    if prices_db is None:
        prices_db = load_prices()

    item = _find_in_db(item_name, prices_db)
    if not item:
        return None

    base = item.get("base_price", 0)
    trade = item.get("trade_price")
    pct = float(discount_percent)
    mult = 1 - pct / 100

    discount_amount = int(base * pct / 100)
    discounted_price = int(base * mult)

    result = {
        "item": item["name"],
        "base_price": base,
        "discount_percent": pct,
        "discount_amount": discount_amount,
        "discounted_price": discounted_price,
    }

    if trade:
        trade_discount_price = int(trade * mult)
        result["trade_price"] = trade
        result["trade_discount_price"] = trade_discount_price

        if trade_discount_price < discounted_price:
            result["best_deal"] = "discounted_trade_price"
            result["best_price"] = trade_discount_price
        else:
            result["best_deal"] = "discounted_base_price"
            result["best_price"] = discounted_price
    else:
        result["best_deal"] = "discounted_base_price"
        result["best_price"] = discounted_price

    result["savings_vs_base"] = base - result["best_price"]

    return result


# ---------------------------------------------------------------------------
# 2. Business ROI
# ---------------------------------------------------------------------------


def calculate_business_roi(item_name, prices_db=None, hours_per_week=10):
    """Calculate ROI for a business/property that generates income.

    Args:
        item_name: Business name (fuzzy matched).
        prices_db: Optional pre-loaded prices dict.
        hours_per_week: Hours played per week (default 10).

    Returns:
        Dict with break-even and ROI analysis, or None if item not found
        or has no known income rate.
    """
    if prices_db is None:
        prices_db = load_prices()

    item = _find_in_db(item_name, prices_db)
    if not item:
        return None

    income = _get_income_rate(item["name"])
    if not income:
        return None

    base = item.get("base_price", 0)
    hourly = income["hourly"]

    weekly_profit = hourly * hours_per_week
    break_even_hours = round(base / hourly, 1) if hourly > 0 else 0
    break_even_weeks = round(break_even_hours / hours_per_week, 2) if hours_per_week > 0 else 0

    # 30-day ROI: assume ~4.3 weeks in 30 days
    weeks_in_30 = 30 / 7
    income_30 = weekly_profit * weeks_in_30
    roi_30 = int((income_30 / base) * 100) if base > 0 else 0

    return {
        "item": item["name"],
        "base_price": base,
        "income_type": income["type"],
        "avg_hourly_profit": hourly,
        "weekly_profit": weekly_profit,
        "break_even_hours": break_even_hours,
        "break_even_weeks": break_even_weeks,
        "roi_30_days": f"{roi_30}%",
        "notes": income.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# 3. Heist ROI
# ---------------------------------------------------------------------------


def calculate_heist_roi(heist_name, required_items=None, prices_db=None,
                        runs_per_week=3):
    """Calculate ROI for a heist setup including required purchases.

    Args:
        heist_name: Heist name (fuzzy matched).
        required_items: Optional list of item names to include in cost
            (e.g. ["Kosatka", "Sparrow Helicopter"]). If None, uses the
            heist's default requirements from the database.
        prices_db: Optional pre-loaded prices dict.
        runs_per_week: Number of heist runs per week (default 3).

    Returns:
        Dict with investment breakdown and ROI, or None if heist not found.
    """
    if prices_db is None:
        prices_db = load_prices()

    # Find the heist
    heist = None
    for name, info in prices_db.get("heists", {}).items():
        if _norm(name) == _norm(heist_name) or _norm(heist_name) in _norm(name):
            heist = {"name": name, **info}
            break
    if not heist:
        return None

    # Determine required items
    if required_items is None:
        required_items = heist.get("requirements", [])

    # Calculate total investment
    investment_breakdown = []
    total_investment = 0
    for req_name in required_items:
        req_item = _find_in_db(req_name, prices_db)
        if req_item:
            price = req_item.get("base_price", 0)
            investment_breakdown.append({"item": req_item["name"], "price": price})
            total_investment += price

    avg_payout = heist.get("avg_payout", 0)
    avg_time = heist.get("avg_time_minutes", 60)

    weekly_income = avg_payout * runs_per_week
    weekly_time = avg_time * runs_per_week
    hourly_rate = int(avg_payout / (avg_time / 60)) if avg_time > 0 else 0

    break_even_runs = round(total_investment / avg_payout, 1) if avg_payout > 0 else 0
    break_even_weeks = round(break_even_runs / runs_per_week, 2) if runs_per_week > 0 else 0

    # 30-day ROI
    weeks_in_30 = 30 / 7
    income_30 = weekly_income * weeks_in_30
    roi_30 = int((income_30 / total_investment) * 100) if total_investment > 0 else 0

    return {
        "heist": heist["name"],
        "investment_breakdown": investment_breakdown,
        "total_investment": total_investment,
        "avg_payout_per_run": avg_payout,
        "avg_time_per_run_minutes": avg_time,
        "runs_per_week": runs_per_week,
        "weekly_income": weekly_income,
        "weekly_time_minutes": weekly_time,
        "break_even_runs": break_even_runs,
        "break_even_weeks": break_even_weeks,
        "hourly_rate": hourly_rate,
        "roi_30_days": f"{roi_30}%",
        "notes": heist.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# 4. Compare investments
# ---------------------------------------------------------------------------


def compare_investments(items_list, prices_db=None, metric="roi_30_days"):
    """Compare multiple purchase options and rank them.

    Args:
        items_list: List of dicts with 'item' and optional 'discount' keys.
            e.g. [{"item": "Kosatka", "discount": 30}, ...]
        prices_db: Optional pre-loaded prices dict.
        metric: Sort metric — "break_even_weeks", "roi_30_days", or
            "hourly_rate".

    Returns:
        Ranked list of dicts with analysis and rank.
    """
    if prices_db is None:
        prices_db = load_prices()

    results = []

    for entry in items_list:
        item_name = entry["item"]
        discount = entry.get("discount", 0)

        item = _find_in_db(item_name, prices_db)
        if not item:
            continue

        base = item.get("base_price", 0)
        effective_price = int(base * (1 - discount / 100)) if discount else base

        # Try business ROI
        biz = calculate_business_roi(item_name, prices_db)
        # Try heist ROI (check if item enables a heist)
        heist_roi = _find_heist_for_item(item_name, prices_db)

        record = {
            "item": item["name"],
            "base_price": base,
            "discount_percent": discount,
            "effective_price": effective_price,
        }

        if heist_roi:
            record["roi_30_days"] = heist_roi["roi_30_days"]
            record["break_even_weeks"] = heist_roi["break_even_weeks"]
            record["hourly_rate"] = heist_roi["hourly_rate"]
            record["reason"] = _ENABLER_ITEMS.get(item["name"], heist_roi.get("notes", ""))
        elif biz:
            record["roi_30_days"] = biz["roi_30_days"]
            record["break_even_weeks"] = biz["break_even_weeks"]
            record["hourly_rate"] = biz["avg_hourly_profit"]
            record["reason"] = biz.get("notes", "")
        else:
            record["roi_30_days"] = "N/A"
            record["break_even_weeks"] = 0
            record["hourly_rate"] = 0
            record["reason"] = _ENABLER_ITEMS.get(
                item["name"], item.get("notes", "Utility/combat vehicle"),
            )

        results.append(record)

    # Sort by metric
    results.sort(key=lambda r: _sort_key(r, metric), reverse=True)

    # Add rank
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return results


# ---------------------------------------------------------------------------
# 5. Purchase recommendation
# ---------------------------------------------------------------------------


def generate_purchase_recommendation(discounts, budget, prices_db=None,
                                     playstyle="mixed"):
    """Generate purchase recommendations based on current discounts and budget.

    Args:
        discounts: List of discount dicts from parser, each with
            'item' and 'discount' keys.
        budget: Available GTA$ budget.
        prices_db: Optional pre-loaded prices dict.
        playstyle: One of "solo", "crew", "mixed", "grinder", "casual".

    Returns:
        Dict with recommendations, total cost, and remaining budget.
    """
    if prices_db is None:
        prices_db = load_prices()

    priorities = PLAYSTYLE_PRIORITIES.get(playstyle, PLAYSTYLE_PRIORITIES["mixed"])

    # Build a map of discounted items
    discount_map = {}
    for d in discounts:
        name = d.get("item", "")
        pct_str = str(d.get("discount", "0"))
        m = re.search(r"(\d+)", pct_str)
        pct = int(m.group(1)) if m else 0
        discount_map[name.lower()] = {"original_name": name, "percent": pct}

    recommendations = []
    alternatives = []
    total_cost = 0
    remaining = budget

    # Score each discounted item
    scored = []
    for disc_lower, disc_info in discount_map.items():
        item = _find_in_db(disc_info["original_name"], prices_db)
        if not item:
            continue

        base = item.get("base_price", 0)
        pct = disc_info["percent"]
        effective = int(base * (1 - pct / 100)) if pct else base

        # Priority score from playstyle
        priority_score = 0
        for i, p_name in enumerate(priorities):
            if _norm(p_name) == _norm(item["name"]) or _norm(p_name) in _norm(item["name"]):
                priority_score = len(priorities) - i
                break

        # ROI score
        roi_score = 0
        income = _get_income_rate(item["name"])
        if income:
            roi_score = income["hourly"] / 10000
        heist = _find_heist_for_item(item["name"], prices_db)
        if heist:
            roi_score = max(roi_score, heist.get("hourly_rate", 0) / 10000)

        # Discount attractiveness
        disc_score = pct / 10

        total_score = priority_score * 3 + roi_score * 2 + disc_score

        scored.append({
            "item": item["name"],
            "effective_price": effective,
            "discount_percent": pct,
            "score": total_score,
            "priority_score": priority_score,
            "base_price": base,
            "notes": item.get("notes", ""),
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Allocate budget
    for s in scored:
        if s["effective_price"] <= remaining:
            priority_label = "HIGH" if s["priority_score"] >= 4 else (
                "MEDIUM" if s["priority_score"] >= 2 else "LOW"
            )

            reason = _build_reason(s, prices_db)

            rec = {
                "priority": priority_label,
                "item": s["item"],
                "base_price": s["base_price"],
                "discounted_price": s["effective_price"],
                "discount_percent": s["discount_percent"],
                "reason": reason,
            }

            # Add ROI info if available
            biz = calculate_business_roi(s["item"], prices_db)
            if biz:
                rec["roi_30_days"] = biz["roi_30_days"]
            heist = _find_heist_for_item(s["item"], prices_db)
            if heist:
                rec["roi_30_days"] = heist["roi_30_days"]

            recommendations.append(rec)
            total_cost += s["effective_price"]
            remaining -= s["effective_price"]
        else:
            alternatives.append({
                "item": s["item"],
                "discounted_price": s["effective_price"],
                "discount_percent": s["discount_percent"],
                "reason": f"Over budget (need ${s['effective_price']:,})",
            })

    return {
        "budget": budget,
        "playstyle": playstyle,
        "recommendations": recommendations,
        "total_cost": total_cost,
        "remaining_budget": remaining,
        "alternative_options": alternatives,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm(name):
    """Quick lowercase normalise for matching."""
    lower = name.lower().strip()
    return re.sub(r"[^a-z0-9\s]", "", lower).strip()


def _find_in_db(item_name, prices_db):
    """Find an item in the prices database by fuzzy name match."""
    q = _norm(item_name)
    # Pass 1: exact
    for cat in ("vehicles", "properties", "heists"):
        for name, info in prices_db.get(cat, {}).items():
            if _norm(name) == q:
                return {"name": name, "category_key": cat, **info}
    # Pass 2: partial
    for cat in ("vehicles", "properties", "heists"):
        for name, info in prices_db.get(cat, {}).items():
            n = _norm(name)
            if q in n or n in q:
                return {"name": name, "category_key": cat, **info}
    return None


def _get_income_rate(item_name):
    """Look up the income rate for an item."""
    for name, rate in INCOME_RATES.items():
        if _norm(name) == _norm(item_name) or _norm(name) in _norm(item_name):
            return rate
    return None


def _find_heist_for_item(item_name, prices_db):
    """Check if an item enables a heist and return that heist's ROI."""
    for hname, hinfo in prices_db.get("heists", {}).items():
        reqs = hinfo.get("requirements", [])
        for req in reqs:
            if _norm(req) == _norm(item_name) or _norm(item_name) in _norm(req):
                return calculate_heist_roi(hname, prices_db=prices_db)
    return None


def _sort_key(record, metric):
    """Extract a numeric sort key from a record for the given metric."""
    val = record.get(metric, 0)
    if isinstance(val, str):
        m = re.search(r"(\d+)", val)
        return int(m.group(1)) if m else 0
    return val


def _build_reason(scored_item, prices_db):
    """Build a human-readable reason string for a recommendation."""
    name = scored_item["item"]
    pct = scored_item["discount_percent"]

    # Check enabler items first
    if name in _ENABLER_ITEMS:
        reason = _ENABLER_ITEMS[name]
        if pct:
            reason += f", {pct}% off this week"
        return reason

    # Check income
    income = _get_income_rate(name)
    if income:
        hourly = income["hourly"]
        itype = income["type"]
        reason = f"{itype.capitalize()} income (${hourly:,}/hr)"
        if pct:
            reason += f", {pct}% off this week"
        return reason

    if pct:
        return f"{pct}% off this week"
    return scored_item.get("notes", "")
