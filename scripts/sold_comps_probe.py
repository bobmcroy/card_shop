from __future__ import annotations

import re
import requests
import sys


def fetch_sold_listings(query: str) -> None:
    url = "https://www.ebay.com/sch/i.html"
    params = {
        "_nkw": query,
        "LH_Sold": "1",
        "LH_Complete": "1",
    }

    r = requests.get(
        url,
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
        timeout=30,
    )
    r.raise_for_status()

    html = r.text

    print("\n=== FINAL URL ===")
    print(r.url)

    print("\n=== QUICK CHECKS ===")
    checks = {
        "contains_sold_word": "sold" in html.lower(),
        "contains_completed_word": "completed" in html.lower(),
        "contains_s_item_title": "s-item__title" in html,
        "contains_s_item_price": "s-item__price" in html,
        "contains_ended_date": "ended" in html.lower(),
    }
    for k, v in checks.items():
        print(f"{k}: {v}")

    print("\n=== SAMPLE MATCHES ===")
    for pattern in [r"s-item__title", r"s-item__price", r"ended", r"Sold items", r"Completed items"]:
        matches = re.findall(pattern, html, flags=re.IGNORECASE)
        print(f"{pattern}: {len(matches)}")

    print("\n=== FIRST 2000 CHARS ===\n")
    print(html[:2000])


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "1991 Stadium Club Ken Griffey Jr #270"
    print("Query:", query)
    fetch_sold_listings(query)