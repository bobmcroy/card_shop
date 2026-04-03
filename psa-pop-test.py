#!/usr/bin/env python3
# psa-pop-test.py
from __future__ import annotations

import sys

from providers.psa_pop_playwright import (
    PopQuery,
    fetch_set_population_rows,
    filter_card_rows,
    pop_row_to_scarcity_summary,
)

from utils.io_utils import build_output_path, write_rows_to_csv
from utils.pretty_table import print_aligned_table
from utils.prompt_utils import autocomplete_object, select_choice, text_input
from utils.psa_sets_index import load_index, get_sets, SetEntry
from pathlib import Path


OUTPUT_COLUMNS = [
    "spec_id",
    "player",
    "card_number",
    "variety",
    "total_pop",
    "pop_10",
    "pop_9",
    "pop_8",
    "pop_7",
    "pop_6",
    "pop_5",
    "pop_4",
    "pop_3",
    "pop_2",
    "pop_1",
]

PROJECT_ROOT = Path(__file__).resolve().parent
SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]
YEARS = list(range(1990, 2001))

def get_pop_output_dir(sport: str) -> Path:
    return PROJECT_ROOT / "data" / "csv_dumps" / "pop_report" / sport.strip().lower()


def prompt_sport_scrollable() -> str:
    return select_choice(
        "Choose Sport:",
        SPORTS,
        default="Baseball",
    )


def prompt_year_scrollable() -> int:
    return int(
        select_choice(
            "Choose Year:",
            [str(y) for y in YEARS],
            default="1991",
        )
    )


def prompt_set_typeahead(sets: list[SetEntry]) -> SetEntry:
    return autocomplete_object(
        "Choose Set (type to filter, Enter to select):",
        sets,
        label_getter=lambda s: s.name.strip(),
        value_getter=lambda s: s.url.rstrip("/").split("/")[-1],
    )


def prompt_player_name() -> str | None:
    return text_input("Enter Player Name (optional — press Enter for all players):")


def prompt_card_number_optional() -> str | None:
    return text_input("Enter Card # (optional — press Enter to skip):")


def main() -> None:
    sport = prompt_sport_scrollable()
    year = prompt_year_scrollable()

    index = load_index()
    sets = get_sets(index, sport, year)

    if not sets:
        print(f"\nNo cached sets found for {sport} {year}.")
        print("Add sets to the local index (data/psa_sets_index.json) and try again.")
        sys.exit(1)

    chosen_set = prompt_set_typeahead(sets)

    print(f"\nSelected Set: {chosen_set.name}")
    print(f"Set URL: {chosen_set.url}\n")

    player = prompt_player_name()
    card_no = prompt_card_number_optional()

    rows = fetch_set_population_rows(
        chosen_set.url,
        headless=False,
        timeout_s=120,
    )

    print("DEBUG: rows returned:", len(rows) if rows else 0)

    q = PopQuery(
        pop_set_url=chosen_set.url,
        player=player or "",
        card_number=card_no,
        variety_contains=None,
    )

    matches = filter_card_rows(rows, q)
    summaries = [pop_row_to_scarcity_summary(r) for r in matches]

    out_csv = build_output_path(
        get_pop_output_dir(sport),
        "psa_pop",
        sport,
        year,
        chosen_set.name,
        player or "all_players",
        card_no or None,
        ext=".csv",
    )

    write_rows_to_csv(
        summaries,
        out_csv,
        field_order=OUTPUT_COLUMNS,
    )

    print(f"\n✅ Wrote CSV: {out_csv} ({len(summaries)} rows)\n")

    print("Aligned preview (first 20 rows):")
    print_aligned_table(
        summaries[:20],
        OUTPUT_COLUMNS,
    )

    if not summaries:
        print("\nNo matches.")
        print("Try:")
        print(" - a shorter player substring (e.g., 'Griffey')")
        print(" - verify you picked the right set/year")
        print(" - leave both Player Name and Card # blank to return the full set")
        print(" - leave Card # blank to return all matches for a player")


if __name__ == "__main__":
    main()