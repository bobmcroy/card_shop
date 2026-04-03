from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Optional


@dataclass
class CompBuckets:
    recent_median_rows: list[dict[str, Any]]
    recent_median_value: Optional[float]

    strong_bin_rows: list[dict[str, Any]]
    strong_bin_value: Optional[float]

    peak_auction_rows: list[dict[str, Any]]
    peak_auction_value: Optional[float]


def _numeric_total(row: dict[str, Any]) -> Optional[float]:
    value = row.get("total_value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _valid_price_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if _numeric_total(row) is not None:
            out.append(row)
    return out


def _median_value(rows: list[dict[str, Any]]) -> Optional[float]:
    vals = [_numeric_total(r) for r in rows]
    clean = [float(v) for v in vals if v is not None]
    if not clean:
        return None
    return round(float(median(clean)), 2)


def _max_value(rows: list[dict[str, Any]]) -> Optional[float]:
    vals = [_numeric_total(r) for r in rows]
    clean = [float(v) for v in vals if v is not None]
    if not clean:
        return None
    return round(max(clean), 2)


def _sort_by_total_desc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (_numeric_total(r) is not None, _numeric_total(r) or 0.0),
        reverse=True,
    )


def build_comp_buckets(rows: list[dict[str, Any]]) -> CompBuckets:
    priced_rows = _valid_price_rows(rows)

    # Bucket 1: broad recent market anchor
    recent_median_rows = priced_rows
    recent_median_value = _median_value(recent_median_rows)

    # Bucket 2: fixed-price / accepted-offer style comps
    strong_bin_rows = [
        row
        for row in priced_rows
        if str(row.get("listing_type", "")).lower() == "bin"
    ]

    # Prefer accepted-offer rows when available; otherwise use all BIN rows
    best_offer_rows = [row for row in strong_bin_rows if bool(row.get("is_best_offer"))]
    strong_bin_source = best_offer_rows if best_offer_rows else strong_bin_rows
    strong_bin_value = _median_value(strong_bin_source)

    # Bucket 3: auction-only comps, highest clears the bucket
    peak_auction_rows = [
        row
        for row in priced_rows
        if str(row.get("listing_type", "")).lower() == "auction"
    ]
    peak_auction_rows = _sort_by_total_desc(peak_auction_rows)
    peak_auction_value = _max_value(peak_auction_rows)

    return CompBuckets(
        recent_median_rows=recent_median_rows,
        recent_median_value=recent_median_value,
        strong_bin_rows=strong_bin_source,
        strong_bin_value=strong_bin_value,
        peak_auction_rows=peak_auction_rows,
        peak_auction_value=peak_auction_value,
    )


def buckets_to_dict(buckets: CompBuckets) -> dict[str, Any]:
    return {
        "recent_median_rows": buckets.recent_median_rows,
        "recent_median_value": buckets.recent_median_value,
        "strong_bin_rows": buckets.strong_bin_rows,
        "strong_bin_value": buckets.strong_bin_value,
        "peak_auction_rows": buckets.peak_auction_rows,
        "peak_auction_value": buckets.peak_auction_value,
    }


def bucket_summary(buckets: CompBuckets) -> dict[str, Any]:
    return {
        "recent_median_count": len(buckets.recent_median_rows),
        "recent_median_value": buckets.recent_median_value,
        "strong_bin_count": len(buckets.strong_bin_rows),
        "strong_bin_value": buckets.strong_bin_value,
        "peak_auction_count": len(buckets.peak_auction_rows),
        "peak_auction_value": buckets.peak_auction_value,
    }