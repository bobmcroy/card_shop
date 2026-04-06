# This is intentionally a probe, not production logic.
# It tests:
# can we query by date window
# do results look like ended listings
# do we get enough signals to separate auction/fixed price
# are we actually seeing sold/completed behavior, or just live listings ending in a window

# scripts/ebay_sold_probe.py
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.ebay_browse import EbayBrowseClient
from utils.config import load_ebay_config


def iso_z(d: dt.datetime) -> str:
    return d.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    cfg = load_ebay_config()
    client = EbayBrowseClient(cfg)

    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=30)

    # This is only testing whether itemEndDate filtering returns anything useful
    # for our comps use case. It does NOT assume these are sold listings.
    filter_expr = f"itemEndDate:[{iso_z(start)}..{iso_z(now)}]"

    query = "1991 Stadium Club Ken Griffey Jr #3"
    data = client.search_items(
        query,
        limit=20,
        filter_expr=filter_expr,
        sort="-price",
    )

    items = data.get("itemSummaries", [])
    print(f"Returned items: {len(items)}")
    print(f"Filter used: {filter_expr}")

    for i, item in enumerate(items, start=1):
        print(f"\n--- Candidate {i} ---")
        print("title:", item.get("title"))
        print("price:", item.get("price"))
        print("buyingOptions:", item.get("buyingOptions"))
        print("condition:", item.get("condition"))
        print("itemEndDate:", item.get("itemEndDate"))
        print("itemWebUrl:", item.get("itemWebUrl"))


if __name__ == "__main__":
    main()