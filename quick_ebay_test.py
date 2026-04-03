from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime, timedelta, timezone

import requests


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_access_token() -> str:
    client_id = get_required_env("EBAY_CLIENT_ID")
    client_secret = get_required_env("EBAY_CLIENT_SECRET")
    env = os.getenv("EBAY_ENV", "production").strip().lower()

    oauth_url = (
        "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        if env == "sandbox"
        else "https://api.ebay.com/identity/v1/oauth2/token"
    )

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    resp = requests.post(
        oauth_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def build_filter(days: int | None, auction_only: bool) -> str | None:
    parts: list[str] = []

    if days and days > 0:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        parts.append(f"itemEndDate:[{iso_z(start)}..{iso_z(now)}]")

    if auction_only:
        parts.append("buyingOptions:{AUCTION}")

    if not parts:
        return None

    return ",".join(parts)


def search_card(query: str, *, limit: int = 25, days: int | None = None, auction_only: bool = False) -> None:
    token = get_access_token()
    env = os.getenv("EBAY_ENV", "production").strip().lower()
    marketplace_id = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US").strip()

    browse_url = (
        "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
        if env == "sandbox"
        else "https://api.ebay.com/buy/browse/v1/item_summary/search"
    )

    filter_expr = build_filter(days, auction_only)

    params = {
        "q": query,
        "limit": limit,
    }
    if filter_expr:
        params["filter"] = filter_expr

    resp = requests.get(
        browse_url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            "Accept": "application/json",
        },
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    items = data.get("itemSummaries", [])

    print("\n=== REQUEST ===")
    print("Query:", query)
    print("Limit:", limit)
    print("Days:", days)
    print("Auction only:", auction_only)
    print("Filter:", filter_expr or "(none)")
    print(f"Returned: {len(items)} items")

    for i, item in enumerate(items, start=1):
        print(f"\n--- Item {i} ---")
        print("Title:", item.get("title"))
        print("Price:", item.get("price"))
        print("Buying Options:", item.get("buyingOptions"))
        print("Condition:", item.get("condition"))
        print("Item URL:", item.get("itemWebUrl"))
        print("End Date:", item.get("itemEndDate"))
        print("Creation Date:", item.get("itemCreationDate"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick eBay Browse card test")
    parser.add_argument("--psa10", action="store_true", help="Append PSA 10 to the query")
    parser.add_argument("--days", type=int, default=None, help="Rolling window in days, e.g. 365")
    parser.add_argument("--limit", type=int, default=25, help="Number of items to return")
    parser.add_argument("--auction-only", action="store_true", help="Restrict to auction listings")
    parser.add_argument("query", nargs="*", help="Card search query")

    args = parser.parse_args()

    query = " ".join(args.query).strip() or "1991 Stadium Club Ken Griffey Jr #3"
    if args.psa10 and "psa 10" not in query.lower():
        query = f"{query} PSA 10"

    search_card(
        query,
        limit=args.limit,
        days=args.days,
        auction_only=args.auction_only,
    )


if __name__ == "__main__":
    main()
