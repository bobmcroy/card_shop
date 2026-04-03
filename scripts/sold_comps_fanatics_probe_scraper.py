#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote_plus, urlparse

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

from providers.fanatics_sold_normalizer import normalize_rows
from providers.ebay_sold_summary import compute_summary
from utils.io_utils import build_output_path, write_rows_to_csv, write_json
from utils.prompt_utils import autocomplete_object, select_choice, text_input, yes_no
from utils.psa_sets_index import load_index, get_sets, SetEntry
from scripts.valuation_probe import run_valuation_flow

CDP_URL = "http://127.0.0.1:9222"
CHROME_DEBUG_PORT = 9222
CHROME_USER_DATA_DIR = "/tmp/chrome-fanatics-debug"
MAC_CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]
YEARS = list(range(1990, 2001))
DEBUG = False
MAX_ITEM_PAGES = 12

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
    "source_market",
    "listing_type",
    "item_id",
    "sales_history_url",
    "guide_price",
    "sale_event",
    "sale_row_label",
    "currency",
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
    "source_market",
    "item_id",
    "sales_history_url",
    "guide_price",
    "sale_event",
    "sale_row_label",
    "currency",
]

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
class FanaticsSoldRow:
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
    source_market: str = "fanatics"
    listing_type: str = ""
    item_id: str = ""
    sales_history_url: str = ""
    guide_price: str = ""
    sale_event: str = ""
    sale_row_label: str = ""
    currency: str = "USD"


def normalize_ws(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _safe_lower(value: str | None) -> str:
    return normalize_ws(value).lower()


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
        raise RuntimeError("Started Chrome, but CDP did not become available on port 9222.")

    print("Debug Chrome is ready.")


def detect_grading(title: str) -> tuple[str, str, str]:
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


def parse_fanatics_item_id(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"/buy-now/([^/?#]+)/", url)
    if m:
        return normalize_ws(m.group(1))
    tail = url.rstrip("/").split("/")
    for part in reversed(tail):
        if re.fullmatch(r"[0-9a-fA-F-]{8,}", part):
            return part
    return ""


def get_comps_output_dir(sport: str) -> Path:
    return PROJECT_ROOT / "data" / "csv_dumps" / "comps" / sport.strip().lower()


def prompt_sport_scrollable() -> str:
    return select_choice("Choose Sport:", SPORTS, default="Baseball")


def prompt_year_scrollable() -> int:
    return int(select_choice("Choose Year:", [str(y) for y in YEARS], default="1991"))


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
        parts.append(search.card_number if search.card_number.startswith("#") else f"#{search.card_number}")
    if search.grade_company:
        parts.append(search.grade_company.upper())
    if search.grade_value:
        parts.append(search.grade_value)
    if search.extra_terms:
        parts.append(search.extra_terms)
    return " ".join(normalize_ws(p) for p in parts if normalize_ws(p))


def build_fanatics_search_urls(search: SearchInput) -> list[str]:
    keywords = build_search_keywords(search)
    encoded = quote_plus(keywords)
    return [
        f"https://www.fanaticscollect.com/search?query={encoded}",
        f"https://www.fanaticscollect.com/search?q={encoded}",
        f"https://www.fanaticscollect.com/sold-items?query={encoded}",
        f"https://www.fanaticscollect.com/sold-items?q={encoded}",
    ]


def _keyword_tokens(search: SearchInput) -> list[str]:
    pieces = [
        str(search.year or ''),
        search.set_name or '',
        search.sport or '',
        search.player_name or '',
        search.card_number or '',
        search.grade_company or '',
        search.grade_value or '',
        search.extra_terms or '',
    ]
    tokens: list[str] = []
    for piece in pieces:
        for token in re.split(r"[^A-Za-z0-9#]+", normalize_ws(piece)):
            token = normalize_ws(token)
            if not token:
                continue
            if token.startswith('#'):
                token = token[1:]
            token_l = token.lower()
            if len(token_l) <= 1:
                continue
            if token_l not in tokens:
                tokens.append(token_l)
    return tokens


def _score_title_match(title: str, tokens: list[str]) -> int:
    title_l = _safe_lower(title)
    score = 0
    for token in tokens:
        if token and token in title_l:
            score += 1
    return score


def _discover_candidate_item_urls(page: Page, search: SearchInput, max_items: int = MAX_ITEM_PAGES) -> list[str]:
    search_urls = build_fanatics_search_urls(search)
    tokens = _keyword_tokens(search)
    candidate_map: dict[str, dict[str, Any]] = {}

    script = r"""
    () => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();

      const nearestTextContainer = (el) => {
        let node = el;
        for (let i = 0; i < 6 && node; i += 1) {
          const text = norm(node.innerText || node.textContent || '');
          if (text && text.length > 20) return text;
          node = node.parentElement;
        }
        return '';
      };

      const anchors = Array.from(document.querySelectorAll('a[href]'));
      const out = [];
      const seen = new Set();

      for (const a of anchors) {
        const href = (a.href || '').trim();
        if (!href) continue;
        if (
          !(
            href.includes('/items/') ||
            href.includes('/buy-now/') ||
            href.includes('/vault-marketplace/') ||
            href.includes('/weekly/') ||
            href.includes('/premier/')
          )
        ) continue;

        const key = href.split('#')[0];
        if (seen.has(key)) continue;
        seen.add(key);

        const anchorText = norm(a.innerText || a.textContent || '');
        const aria = norm(a.getAttribute('aria-label') || '');
        const titleAttr = norm(a.getAttribute('title') || '');
        const containerText = nearestTextContainer(a);

        out.push({
          href: key,
          title: anchorText || aria || titleAttr || containerText,
          anchor_text: anchorText,
          container_text: containerText,
        });
      }
      return out;
    }
    """

    for idx, url in enumerate(search_urls, start=1):
        if DEBUG:
            print(f"FANATICS SEARCH {idx} | {url}")
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_load_state('networkidle', timeout=60000)
            page.wait_for_timeout(2500)
            page.bring_to_front()
        except Exception:
            continue

        try:
            raw_candidates = page.evaluate(script)
        except Exception:
            raw_candidates = []

        for entry in raw_candidates:
            href = normalize_ws(str(entry.get('href') or ''))
            title = normalize_ws(str(entry.get('title') or ''))
            container_text = normalize_ws(str(entry.get('container_text') or ''))
            if not href:
                continue

            score = _score_title_match(title or container_text, tokens)

            if score <= 0 and any(route in href for route in ['/weekly/', '/premier/', '/items/', '/buy-now/', '/vault-marketplace/']):
                score = 1

            existing = candidate_map.get(href)
            if existing is None or score > existing['score']:
                candidate_map[href] = {
                    'href': href,
                    'title': title or container_text,
                    'score': score,
                }

        if candidate_map:
            break

    ranked = sorted(candidate_map.values(), key=lambda x: (-int(x['score']), x['title'].lower(), x['href']))
    filtered = [x['href'] for x in ranked if x['score'] > 0]
    if not filtered:
        filtered = [x['href'] for x in ranked]
    return filtered[:max_items]


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
        "fanatics",
    ]

    raw_csv = build_output_path(out_dir, *base_parts, "raw", ext=".csv")
    normalized_csv = build_output_path(out_dir, *base_parts, "normalized", ext=".csv")
    summary_json = build_output_path(out_dir, *base_parts, "summary", ext=".json")
    return raw_csv, normalized_csv, summary_json


def build_valuation_defaults(search: SearchInput) -> dict[str, Any]:
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


def _extract_json_ld_records(page: Page) -> list[dict[str, Any]]:
    try:
        payloads = page.locator('script[type="application/ld+json"]').all_text_contents()
    except Exception:
        payloads = []

    records: list[dict[str, Any]] = []
    for payload in payloads:
        text = normalize_ws(payload)
        if not text:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue
        if isinstance(data, dict):
            records.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    records.append(item)
    return records


def _json_ld_title(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("@type") in {"Product", "Thing"} and normalize_ws(str(record.get("name") or "")):
            return normalize_ws(str(record.get("name") or ""))
    return ""


def _json_ld_image(records: list[dict[str, Any]]) -> str:
    for record in records:
        image = record.get("image")
        if isinstance(image, str) and normalize_ws(image):
            return normalize_ws(image)
        if isinstance(image, list):
            for value in image:
                if isinstance(value, str) and normalize_ws(value):
                    return normalize_ws(value)
    return ""


def _json_ld_offers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for record in records:
        offer = record.get("offers")
        if isinstance(offer, dict):
            offers.append(offer)
        elif isinstance(offer, list):
            offers.extend([x for x in offer if isinstance(x, dict)])
    return offers


def _extract_title(page: Page, records: list[dict[str, Any]]) -> str:
    candidates = [
        _json_ld_title(records),
    ]
    selectors = [
        "h1",
        '[data-testid="listing-title"]',
        '[data-testid="product-title"]',
    ]
    for selector in selectors:
        try:
            text = normalize_ws(page.locator(selector).first.inner_text(timeout=1000))
        except Exception:
            text = ""
        if text:
            candidates.append(text)
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def _extract_image_url(page: Page, records: list[dict[str, Any]]) -> str:
    image = _json_ld_image(records)
    if image:
        return image
    selectors = [
        'img[src*="fanaticscollect"]',
        'img[src*="cloudfront"]',
        'img',
    ]
    for selector in selectors:
        try:
            src = normalize_ws(page.locator(selector).first.get_attribute("src", timeout=1000) or "")
        except Exception:
            src = ""
        if src:
            return src
    return ""


def _extract_listing_type(page: Page, item_url: str) -> str:
    path = _safe_lower(urlparse(item_url).path)
    if "/buy-now/" in path:
        return "fanatics_buy_now"
    try:
        body_text = _safe_lower(page.locator("body").inner_text(timeout=1000))
    except Exception:
        body_text = ""
    if "premier auction" in body_text:
        return "fanatics_premier_auction"
    if "weekly auction" in body_text:
        return "fanatics_weekly_auction"
    if "auction" in body_text:
        return "fanatics_auction"
    return "fanatics"


def _extract_guide_price(page: Page) -> str:
    body_html = ""
    try:
        body_html = page.content()
    except Exception:
        pass
    patterns = [
        re.compile(r"Guide Price[^$]{0,50}(\$\s?\d[\d,]*(?:\.\d{2})?)", re.I),
        re.compile(r"Estimated Value[^$]{0,50}(\$\s?\d[\d,]*(?:\.\d{2})?)", re.I),
    ]
    for pattern in patterns:
        m = pattern.search(body_html)
        if m:
            return normalize_ws(m.group(1)).replace("$ ", "$")
    return ""


def _extract_sales_history(page: Page) -> list[dict[str, str]]:
    script = r'''
    () => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      const results = [];
      const seen = new Set();

      const moneyRe = /\$\s?\d[\d,]*(?:\.\d{2})?/;
      const dateRe = /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}/i;

      const rows = Array.from(document.querySelectorAll('tr, li, div, section'));
      for (const row of rows) {
        const text = norm(row.innerText || row.textContent || '');
        if (!text) continue;
        const hasDate = dateRe.test(text);
        const priceMatch = text.match(moneyRe);
        if (!hasDate || !priceMatch) continue;

        const dateMatch = text.match(dateRe);
        const dateText = dateMatch ? `Sold ${dateMatch[0]}` : '';
        const price = priceMatch ? priceMatch[0].replace('$ ', '$') : '';
        if (!dateText || !price) continue;

        const key = `${dateText}|${price}|${text}`;
        if (seen.has(key)) continue;
        seen.add(key);

        results.push({
          sold_date: dateText,
          price,
          sale_row_label: text,
          sale_event: /premier auction/i.test(text)
            ? 'Premier Auction'
            : /weekly auction/i.test(text)
              ? 'Weekly Auction'
              : /buy now/i.test(text)
                ? 'Buy Now'
                : ''
        });
      }

      return results;
    }
    '''
    try:
        return page.evaluate(script)
    except Exception:
        return []


def scrape_fanatics_item(page: Page, item_url: str) -> list[FanaticsSoldRow]:
    if DEBUG:
        print("Navigating:", item_url)

    page.goto(item_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(2000)
    page.bring_to_front()

    records = _extract_json_ld_records(page)
    title = _extract_title(page, records)
    image_url = _extract_image_url(page, records)
    listing_type = _extract_listing_type(page, item_url)
    guide_price = _extract_guide_price(page)
    item_id = parse_fanatics_item_id(item_url)
    graded, grader, grade = detect_grading(title)

    offers = _json_ld_offers(records)
    default_currency = "USD"
    for offer in offers:
        currency = normalize_ws(str(offer.get("priceCurrency") or ""))
        if currency:
            default_currency = currency
            break

    sales_rows = _extract_sales_history(page)
    if not sales_rows:
        fallback_price = ""
        for offer in offers:
            raw_price = normalize_ws(str(offer.get("price") or ""))
            if raw_price:
                fallback_price = raw_price if raw_price.startswith("$") else f"${raw_price}"
                break
        if fallback_price:
            sales_rows = [{
                "sold_date": "",
                "price": fallback_price,
                "sale_row_label": "Current or fallback page price",
                "sale_event": "",
            }]

    out: list[FanaticsSoldRow] = []
    for sale in sales_rows:
        price = normalize_ws(sale.get("price") or "")
        sold_date = normalize_ws(sale.get("sold_date") or "")
        sale_row_label = normalize_ws(sale.get("sale_row_label") or "")
        sale_event = normalize_ws(sale.get("sale_event") or "")

        out.append(
            FanaticsSoldRow(
                title=title,
                price=price,
                sold_date=sold_date,
                graded=graded,
                grader=grader,
                grade=grade,
                auction="Y" if "auction" in _safe_lower(sale_event or listing_type) else "N",
                best_offer="N",
                shipping="$0.00",
                seller="fanatics collect",
                condition="",
                item_url=item_url,
                image_url=image_url,
                source_market="fanatics",
                listing_type=listing_type,
                item_id=item_id,
                sales_history_url=item_url,
                guide_price=guide_price,
                sale_event=sale_event,
                sale_row_label=sale_row_label,
                currency=default_currency or "USD",
            )
        )

    return out


def main() -> None:
    search = prompt_search_input()
    search_keywords = build_search_keywords(search)
    raw_csv_path, normalized_csv_path, summary_json_path = build_output_paths(search)

    print(f"\nSearch keywords: {search_keywords}")
    print(f"Raw CSV: {raw_csv_path}")
    print(f"Normalized CSV: {normalized_csv_path}")
    print(f"Summary JSON: {summary_json_path}\n")

    raw_rows: list[FanaticsSoldRow] = []
    with sync_playwright() as p:
        launch_debug_chrome_if_needed()
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = get_fresh_page(browser)

        candidate_urls = _discover_candidate_item_urls(page, search, max_items=MAX_ITEM_PAGES)
        print(f"Fanatics candidate item pages: {len(candidate_urls)}")
        for idx, url in enumerate(candidate_urls, start=1):
            print(f"FANATICS ITEM {idx} | {url}")
            item_rows = scrape_fanatics_item(page, url)
            print(f"  sales rows extracted={len(item_rows)}")
            raw_rows.extend(item_rows)

    if not raw_rows:
        print("\nNo Fanatics sold-item pages were discovered from the prompt-based search.")
        print("Try broadening the inputs:")
        print(" - remove grader/grade filters")
        print(" - clear card #")
        print(" - shorten player name")
        print(" - use fewer extra terms")
        sys.exit(1)

    raw_dict_rows = [asdict(row) for row in raw_rows]
    normalized_rows = normalize_rows(raw_dict_rows)
    summary = compute_summary(normalized_rows)

    final_raw_csv = write_rows_to_csv(raw_dict_rows, raw_csv_path, field_order=RAW_OUTPUT_COLUMNS)
    final_normalized_csv = write_rows_to_csv(normalized_rows, normalized_csv_path, field_order=NORMALIZED_OUTPUT_COLUMNS)
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
