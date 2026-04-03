#!/usr/bin/env python3
# psa-set-add.py
from __future__ import annotations

from utils.psa_sets_index import load_index, save_index, add_set

SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]


def main():
    print("Add PSA Pop Set to local index\n")

    sport = input("Sport (Baseball/Football/Basketball/Hockey):\n> ").strip()
    if sport not in SPORTS:
        raise SystemExit(f"Invalid sport. Choose one of: {', '.join(SPORTS)}")

    year_raw = input("Year (1990-2000):\n> ").strip()
    if not year_raw.isdigit():
        raise SystemExit("Year must be a number.")
    year = int(year_raw)

    name = input("Set Name (e.g., Upper Deck, Fleer Ultra, Stadium Club):\n> ").strip()
    if not name:
        raise SystemExit("Set name required.")

    url = input("PSA Pop Set URL (ends with /<setId>):\n> ").strip()
    if not (url.startswith("https://www.psacard.com/pop/") and url.rstrip("/").split("/")[-1].isdigit()):
        raise SystemExit("That doesn't look like a PSA Pop set URL.")

    idx = load_index()
    add_set(idx, sport, year, name, url)
    save_index(idx)

    print("\n✅ Saved to data/psa_sets_index.json")


if __name__ == "__main__":
    main()