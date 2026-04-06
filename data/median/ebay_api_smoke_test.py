# scripts/ebay_api_smoke_test.py
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.ebay_browse import EbayBrowseClient
from utils.config import load_ebay_config


def main() -> None:
    cfg = load_ebay_config()
    client = EbayBrowseClient(cfg)

    query = "1991 Stadium Club Ken Griffey Jr #3"
    data = client.search_items(query, limit=5)

    print("\n=== TOP-LEVEL KEYS ===")
    print(sorted(data.keys()))

    items = data.get("itemSummaries", [])
    print(f"\nReturned items: {len(items)}")

    for i, item in enumerate(items, start=1):
        print(f"\n--- Item {i} ---")
        print("title:", item.get("title"))
        print("price:", item.get("price"))
        print("buyingOptions:", item.get("buyingOptions"))
        print("condition:", item.get("condition"))
        print("itemWebUrl:", item.get("itemWebUrl"))
        print("itemEndDate:", item.get("itemEndDate"))
        print("itemCreationDate:", item.get("itemCreationDate"))

    out = ROOT / "data" / "ebay_smoke_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nSaved raw response to: {out}")


if __name__ == "__main__":
    main()