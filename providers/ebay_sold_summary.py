from __future__ import annotations

from statistics import median
from typing import Any, Dict, List, Optional


def _vals(rows: List[Dict[str, Any]], key: str = "total_value") -> List[float]:
    values: List[float] = []
    for row in rows:
        val = row.get(key)
        if isinstance(val, (int, float)):
            values.append(float(val))
    return sorted(values)


def compute_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_vals = _vals(rows)

    auction_rows = [r for r in rows if r.get("listing_type") == "auction"]
    auction_vals = _vals(auction_rows)

    offer_rows = [r for r in rows if r.get("is_best_offer") is True]
    offer_vals = _vals(offer_rows)

    bin_rows = [r for r in rows if r.get("listing_type") == "bin"]
    bin_vals = _vals(bin_rows)

    return {
        "row_count": len(rows),
        "priced_row_count": len(all_vals),
        "median_total_value": round(median(all_vals), 2) if all_vals else None,
        "max_total_value": round(max(all_vals), 2) if all_vals else None,
        "auction_count": len(auction_rows),
        "auction_peak_value": round(max(auction_vals), 2) if auction_vals else None,
        "best_offer_count": len(offer_rows),
        "best_offer_median_value": round(median(offer_vals), 2) if offer_vals else None,
        "bin_count": len(bin_rows),
        "bin_median_value": round(median(bin_vals), 2) if bin_vals else None,
    }