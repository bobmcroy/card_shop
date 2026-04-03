#!/usr/bin/env python3
from __future__ import annotations

import sys
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple
from urllib.parse import urlencode

from playwright.sync_api import (
    sync_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

# Add project root so imports like `from utils...` work when run as a script
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.ebay_sold_normalizer import normalize_rows
from providers.ebay_sold_summary import compute_summary
from utils.io_utils import build_output_path, write_rows_to_csv, write_json
from utils.prompt_utils import autocomplete_object, select_choice, text_input, yes_no
from utils.psa_sets_index import load_index, get_sets, SetEntry
from scripts.valuation_probe import run_valuation_flow

CDP_URL = "http://127.0.0.1:9222"
CHROME_DEBUG_PORT = 9222
CHROME_USER_DATA_DIR = "/tmp/chrome-ebay-debug"
MAC_CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MAX_PAGES = 10
DEBUG = False
SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]
YEARS = list(range(1990, 2001))

RAW_OUTPUT_COLUMNS = [
    "title",
    "price",
    "sold_date",
    "graded",
    "grader",
    "grade",
    "auction",
    "best_offer",
    "shipping",
    "seller",
    "condition",
    "item_url",
    "image_url",
]

NORMALIZED_OUTPUT_COLUMNS = [
    "title",
    "price",
    "shipping",
    "sold_date",
    "seller",
    "condition",
    "item_url",
    "image_url",
    "graded",
    "grader",
    "grade",
    "auction",
    "best_offer",
    "price_value",
    "shipping_value",
    "total_value",
    "sold_date_value",
    "listing_type",
    "is_best_offer",
    "is_graded",
    "grader_norm",
    "grade_value",
    "card_number_guess",
]


@dataclass
class SearchInput:
    sport: str
    year: int
    set_name: str
    player_name: str
    card_number: str = ""
    grade_company: str = ""
    grade_value: str = ""
    extra_terms: str = ""


@dataclass
class SoldRow:
    title: str
    price: str
    sold_date: str
    graded: str
    grader: str
    grade: str
    auction: str
    best_offer: str
    shipping: str
    seller: str
    condition: str
    item_url: str
    image_url: str


GRADING_REGEXES = [
    re.compile(
        r"\b(PSA|BGS|SGC|CSG|BVG|CGC|HGA|TAG|ISA|GMA)\s*(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1|AUTH|AUTHENTIC)\b",
        re.I,
    ),
    re.compile(
        r"\b(PSA|BGS|SGC|CSG|BVG|CGC|HGA|TAG|ISA|GMA)\b.*?\b(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1|AUTH|AUTHENTIC)\b",
        re.I,
    ),
]


def is_cdp_available(cdp_url: str = CDP_URL) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_cdp(cdp_url: str = CDP_URL, timeout_s: int = 15) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if is_cdp_available(cdp_url):
            return True
        time.sleep(0.5)
    return False


def launch_debug_chrome_if_needed() -> None:
    if is_cdp_available(CDP_URL):
        print("CDP Chrome already available on port 9222.")
        return

    chrome_path = Path(MAC_CHROME_BIN)
    if not chrome_path.exists():
        raise RuntimeError(
            f"Chrome not found at expected path: {MAC_CHROME_BIN}\n"
            "Update MAC_CHROME_BIN in the script if your local Chrome path is different."
        )

    print("CDP Chrome not detected. Launching debug Chrome...")

    subprocess.Popen(
        [
            str(chrome_path),
            f"--remote-debugging-port={CHROME_DEBUG_PORT}",
            f"--user-data-dir={CHROME_USER_DATA_DIR}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if not wait_for_cdp(CDP_URL, timeout_s=15):
        raise RuntimeError(
            "Started Chrome, but CDP did not become available on port 9222."
        )

    print("Debug Chrome is ready.")


def normalize_ws(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def extract_item_id(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"/itm/(?:[^/]+/)?(\d{9,15})", url)
    if m:
        return m.group(1)
    return ""


def canonicalize_url(url: str) -> str:
    if not url:
        return ""

    item_id = extract_item_id(url)
    if item_id:
        return f"https://www.ebay.com/itm/{item_id}"

    clean = url.split("?", 1)[0].split("#", 1)[0]
    return clean.strip()


def detect_grading(title: str) -> Tuple[str, str, str]:
    t = normalize_ws(title).upper()

    for rx in GRADING_REGEXES:
        m = rx.search(t)
        if m:
            grader = m.group(1).upper()
            grade = m.group(2).upper()
            if grade == "AUTHENTIC":
                grade = "AUTH"
            return "Y", grader, grade

    return "N", "", ""


def get_comps_output_dir(sport: str) -> Path:
    return PROJECT_ROOT / "data" / "csv_dumps" / "comps" / sport.strip().lower()


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


def prompt_player_name_optional() -> str:
    return text_input("Enter Player Name (optional — press Enter for none):") or ""


def prompt_card_number_optional() -> str:
    return text_input("Enter Card # (optional — press Enter to skip):") or ""


def prompt_grade_company_optional() -> str:
    return text_input("Enter Grade Company (optional — PSA/SGC/BGS/etc):") or ""


def prompt_grade_value_optional() -> str:
    return text_input("Enter Grade Value (optional — 10/9/8.5/etc):") or ""


def prompt_extra_terms_optional() -> str:
    return text_input("Enter Extra Terms (optional):") or ""


def prompt_run_valuations_now(normalized_row_count: int) -> bool:
    return yes_no(
        (
            "Run valuations now?\n"
            "This will use the normalized CSV just created, let you filter comps, "
            "and print a table of every row used for valuation.\n"
            f"Normalized rows available: {normalized_row_count}"
        ),
        default=True,
    )


def prompt_search_input() -> SearchInput:
    sport = prompt_sport_scrollable()
    year = prompt_year_scrollable()

    index = load_index()
    sets = get_sets(index, sport, year)

    if not sets:
        print(f"\nNo cached sets found for {sport} {year}.")
        print("Add sets to data/psa_sets_index.json and try again.")
        sys.exit(1)

    chosen_set = prompt_set_typeahead(sets)

    print(f"\nSelected Set: {chosen_set.name}")
    print(f"Set URL: {chosen_set.url}\n")

    player_name = prompt_player_name_optional()
    card_number = prompt_card_number_optional()
    grade_company = prompt_grade_company_optional()
    grade_value = prompt_grade_value_optional()
    extra_terms = prompt_extra_terms_optional()

    return SearchInput(
        sport=sport,
        year=year,
        set_name=chosen_set.name,
        player_name=player_name,
        card_number=card_number,
        grade_company=grade_company,
        grade_value=grade_value,
        extra_terms=extra_terms,
    )


def build_search_keywords(search: SearchInput) -> str:
    parts: List[str] = []

    if search.year:
        parts.append(str(search.year))

    if search.set_name:
        parts.append(search.set_name)

    if search.sport:
        parts.append(search.sport)

    if search.player_name:
        parts.append(search.player_name)

    if search.card_number:
        if search.card_number.startswith("#"):
            parts.append(search.card_number)
        else:
            parts.append(f"#{search.card_number}")

    if search.grade_company:
        parts.append(search.grade_company.upper())

    if search.grade_value:
        parts.append(search.grade_value)

    if search.extra_terms:
        parts.append(search.extra_terms)

    return " ".join(normalize_ws(p) for p in parts if normalize_ws(p))


def build_search_url(search: SearchInput) -> str:
    keywords = build_search_keywords(search)

    params = {
        "_nkw": keywords,
        "LH_Sold": "1",
        "LH_Complete": "1",
        "_sop": "13",
    }

    return "https://www.ebay.com/sch/i.html?" + urlencode(params)


def build_output_paths(search: SearchInput) -> tuple[Path, Path, Path]:
    out_dir = get_comps_output_dir(search.sport)

    base_parts = [
        search.sport,
        search.year,
        search.set_name,
        search.player_name,
        search.card_number or None,
        search.grade_company or None,
        search.grade_value or None,
        search.extra_terms or None,
    ]

    raw_csv = build_output_path(out_dir, *base_parts, "raw", ext=".csv")
    normalized_csv = build_output_path(out_dir, *base_parts, "normalized", ext=".csv")
    summary_json = build_output_path(out_dir, *base_parts, "summary", ext=".json")
    return raw_csv, normalized_csv, summary_json


def build_valuation_defaults(search: SearchInput) -> dict[str, Any]:
    """
    Carry forward scraper search inputs into valuation so the user
    does not need to re-enter the same card context.
    """
    require_graded: Optional[bool] = None
    if search.grade_company or search.grade_value:
        require_graded = True

    search_keywords = build_search_keywords(search)

    return {
        "player_name": search.player_name or "",
        "card_number": search.card_number or "",
        "grader": search.grade_company or "",
        "grade_value": search.grade_value or "",
        "require_graded": require_graded,
        "search_keywords": search_keywords,
        "search_string": search_keywords,
    }


def get_fresh_page(browser: Browser) -> Page:
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError("No browser contexts found via CDP")

    ctx = contexts[0]
    page = ctx.new_page()
    page.bring_to_front()
    return page


def wait_for_results(page: Page) -> None:
    selectors = [
        ".s-card",
        "a.s-card__link",
        "a[href*='/itm/']",
    ]

    last_error = None
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=10000)
            return
        except PlaywrightTimeoutError as e:
            last_error = e

    raise RuntimeError(f"Could not detect eBay results container: {last_error}")


def goto_page(page: Page, search_url: str, page_num: int) -> None:
    if page_num == 1:
        url = search_url
    else:
        joiner = "&" if "?" in search_url else "?"
        url = f"{search_url}{joiner}_pgn={page_num}"

    if DEBUG:
        print("Navigating:", url)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    page.bring_to_front()


def extract_rows_from_page(page: Page) -> List[SoldRow]:
    raw_rows = page.evaluate(
        r"""
        () => {
            const norm = s => (s || "").replace(/\s+/g, " ").trim();

            const uniq = arr => {
                const out = [];
                const seen = new Set();
                for (const x of arr) {
                    if (!x) continue;
                    if (seen.has(x)) continue;
                    seen.add(x);
                    out.push(x);
                }
                return out;
            };

            const extractSoldDate = txt => {
                const t = norm(txt);
                const m = t.match(/\bSold\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\b/i);
                return m ? `Sold ${m[1]}` : "";
            };

            const extractPrice = txt => {
                const t = norm(txt);
                const soldMatch = t.match(/\bSold\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\b/i);
                const searchText = soldMatch ? t.slice(soldMatch.index + soldMatch[0].length) : t;

                const all = [];
                const regex = /(?:US\s*)?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)/gi;
                let m;
                while ((m = regex.exec(searchText)) !== null) {
                    all.push(`$${m[1]}`);
                }

                const unique = uniq(all);
                return unique.length ? unique[0] : "";
            };

            const extractShipping = txt => {
                const t = norm(txt);

                if (/\bFree delivery\b/i.test(t) || /\bFree shipping\b/i.test(t)) {
                    return "$0.00";
                }

                const m =
                    t.match(/\+\s*(?:US\s*)?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+(?:delivery|shipping)\b/i) ||
                    t.match(/\b(?:delivery|shipping)\s+\+\s*(?:US\s*)?\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\b/i);

                return m ? `$${m[1]}` : "";
            };

            const extractSeller = txt => {
                const t = norm(txt);

                let m = t.match(/\bSell one like this\s+([A-Za-z0-9._-]+)\s+\d{1,3}(?:\.\d+)?%\s+positive\b/i);
                if (m) return m[1];

                m = t.match(/\b([A-Za-z0-9._-]+)\s+\d{1,3}(?:\.\d+)?%\s+positive\b/i);
                if (m) return m[1];

                return "";
            };

            const extractCondition = txt => {
                const t = norm(txt);

                const known = [
                    "Brand New",
                    "New",
                    "Like New",
                    "Very Good",
                    "Good",
                    "Acceptable",
                    "Pre-Owned",
                    "Ungraded",
                    "Used",
                    "Not Specified"
                ];

                for (const c of known) {
                    const rx = new RegExp(`\\b${c.replace("-", "\\-")}\\b`, "i");
                    if (rx.test(t)) return c;
                }

                return "";
            };

            const isAuction = txt => /\b\d+\s+bids?\b/i.test(txt);
            const isBestOffer = txt => /\bor Best Offer\b/i.test(txt);

            const extractImageUrl = card => {
                const img =
                    card.querySelector("img.s-card__image-img") ||
                    card.querySelector(".s-card__image img") ||
                    card.querySelector("img");
                if (!img) return "";
                return (
                    img.getAttribute("src") ||
                    img.getAttribute("data-src") ||
                    img.getAttribute("data-zoom-src") ||
                    img.getAttribute("data-imageurl") ||
                    ""
                ).trim();
            };

            const cards = Array.from(document.querySelectorAll(".s-card"));
            const rows = [];
            const seen = new Set();

            for (const card of cards) {
                const titleLink =
                    card.querySelector("a.s-card__link:not(.image-treatment)") ||
                    card.querySelector("a.s-card__link") ||
                    card.querySelector("a[href*='/itm/']:not(.image-treatment)") ||
                    card.querySelector("a[href*='/itm/']");

                if (!titleLink) continue;

                const href = titleLink.href || "";
                if (!href.includes("/itm/")) continue;
                if (href.includes("/itm/i.html")) continue;

                const itemMatch = href.match(/\/itm\/(?:[^/]+\/)?(\d{9,15})/);
                const itemId = itemMatch ? itemMatch[1] : href;
                if (seen.has(itemId)) continue;
                seen.add(itemId);

                let title = norm(titleLink.innerText || titleLink.textContent || "");
                title = title.replace(/\bOpens in a new window or tab\b/i, "").trim();
                title = title.replace(/^New Listing\s+/i, "").trim();

                const cardText = norm(card.innerText || card.textContent || "");
                if (!title) continue;

                rows.push({
                    title,
                    price: extractPrice(cardText),
                    sold_date: extractSoldDate(cardText),
                    auction: isAuction(cardText) ? "Y" : "N",
                    best_offer: isBestOffer(cardText) ? "Y" : "N",
                    shipping: extractShipping(cardText),
                    seller: extractSeller(cardText),
                    condition: extractCondition(cardText),
                    item_url: href,
                    image_url: extractImageUrl(card)
                });
            }

            return rows;
        }
        """
    )

    rows: List[SoldRow] = []

    for r in raw_rows:
        title = normalize_ws(r.get("title"))
        price = normalize_ws(r.get("price"))
        sold_date = normalize_ws(r.get("sold_date"))
        auction = normalize_ws(r.get("auction")) or "N"
        best_offer = normalize_ws(r.get("best_offer")) or "N"
        shipping = normalize_ws(r.get("shipping"))
        seller = normalize_ws(r.get("seller"))
        condition = normalize_ws(r.get("condition"))
        url = normalize_ws(r.get("item_url"))
        image_url = normalize_ws(r.get("image_url"))

        if not title or not url:
            continue

        graded, grader, grade = detect_grading(title)

        rows.append(
            SoldRow(
                title=title,
                price=price,
                sold_date=sold_date,
                graded=graded,
                grader=grader,
                grade=grade,
                auction=auction,
                best_offer=best_offer,
                shipping=shipping,
                seller=seller,
                condition=condition,
                item_url=url,
                image_url=image_url,
            )
        )

    return rows


def scrape_all_pages(page: Page, search_url: str, max_pages: int = MAX_PAGES) -> List[SoldRow]:
    all_rows: List[SoldRow] = []
    seen: Set[str] = set()

    for page_num in range(1, max_pages + 1):
        goto_page(page, search_url, page_num)
        wait_for_results(page)

        rows = extract_rows_from_page(page)

        added = 0
        for row in rows:
            key = extract_item_id(row.item_url) or row.item_url
            if key not in seen:
                seen.add(key)
                all_rows.append(row)
                added += 1

        print(f"PAGE {page_num} | extracted={len(rows)} new={added} total={len(all_rows)}")

        if not rows:
            print(f"Stopping early: page {page_num} returned no rows.")
            break

        if added == 0:
            print(f"Stopping early: page {page_num} produced no new items.")
            break

    return all_rows


def main() -> None:
    search = prompt_search_input()
    search_keywords = build_search_keywords(search)
    search_url = build_search_url(search)
    raw_csv_path, normalized_csv_path, summary_json_path = build_output_paths(search)

    print(f"\nSearch keywords: {search_keywords}")
    print(f"Search URL: {search_url}")
    print(f"Raw CSV: {raw_csv_path}")
    print(f"Normalized CSV: {normalized_csv_path}")
    print(f"Summary JSON: {summary_json_path}\n")

    with sync_playwright() as p:
        launch_debug_chrome_if_needed()
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = get_fresh_page(browser)
        raw_rows = scrape_all_pages(page, search_url=search_url)

    raw_dict_rows = [asdict(row) for row in raw_rows]
    normalized_rows = normalize_rows(raw_dict_rows)

    image_by_item_url: dict[str, str] = {}
    for row in raw_dict_rows:
        item_url = normalize_ws(str(row.get("item_url") or ""))
        image_url = normalize_ws(str(row.get("image_url") or ""))
        if item_url and image_url and item_url not in image_by_item_url:
            image_by_item_url[item_url] = image_url

    for row in normalized_rows:
        item_url = normalize_ws(str(row.get("item_url") or ""))
        if item_url:
            row["image_url"] = image_by_item_url.get(item_url, "")
        else:
            row["image_url"] = ""

    summary = compute_summary(normalized_rows)

    final_raw_csv = write_rows_to_csv(
        raw_dict_rows,
        raw_csv_path,
        field_order=RAW_OUTPUT_COLUMNS,
    )

    final_normalized_csv = write_rows_to_csv(
        normalized_rows,
        normalized_csv_path,
        field_order=NORMALIZED_OUTPUT_COLUMNS,
    )

    final_summary_json = write_json(summary, summary_json_path)

    print(f"\nRaw CSV written: {final_raw_csv.resolve()}")
    print(f"Normalized CSV written: {final_normalized_csv.resolve()}")
    print(f"Summary JSON written: {final_summary_json.resolve()}")
    print(f"Rows scraped: {len(raw_dict_rows)}")
    print(f"Rows normalized: {len(normalized_rows)}")
    print(f"Summary: {summary}")

    run_valuations_now = prompt_run_valuations_now(len(normalized_rows))

    if run_valuations_now:
        valuation_defaults = build_valuation_defaults(search)

        print("\nStarting valuation flow with inherited search context...\n")
        print(f"Player:          {valuation_defaults.get('player_name') or '(none)'}")
        print(f"Card #:          {valuation_defaults.get('card_number') or '(none)'}")
        print(f"Grader filter:   {valuation_defaults.get('grader') or '(none)'}")
        print(f"Grade filter:    {valuation_defaults.get('grade_value') or '(none)'}")

        require_graded = valuation_defaults.get("require_graded")
        if require_graded is True:
            graded_label = "graded only"
        elif require_graded is False:
            graded_label = "raw only"
        else:
            graded_label = "any"

        print(f"Graded filter:   {graded_label}\n")

        run_valuation_flow(
            normalized_csv_path=final_normalized_csv,
            sport=search.sport,
            year_filter=str(search.year),
            inherited_filters=valuation_defaults,
        )

    else:
        print("\nValuation skipped.")
        print("To run valuations later:")
        print("  python3 scripts/valuation_probe.py")
        print(f"Then select: {final_normalized_csv.resolve()}")


if __name__ == "__main__":
    main()