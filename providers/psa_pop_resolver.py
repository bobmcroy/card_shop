# providers/psa_pop_resolver.py
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.psacard.com"

# P1 choices
SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]

# PSA Pop category landing pages:
# https://www.psacard.com/pop/<slug>/<categoryId>
SPORT_TO_CATEGORY: Dict[str, tuple[str, str]] = {
    "Baseball": ("baseball-cards", "20003"),
    "Football": ("football-cards", "20014"),
    "Basketball": ("basketball-cards", "20009"),
    "Hockey": ("hockey-cards", "20012"),
}

# Persistent Playwright profile shared with psa_pop_playwright.py
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", ".pw_psa_profile")


@dataclass
class PopSet:
    name: str
    url: str


def _extract_year_url(hrefs: list[str], year: int) -> Optional[str]:
    # ex: /pop/baseball-cards/1991/21017
    pat = re.compile(rf"^/pop/[^/]+/{year}/\d+$")
    for h in hrefs:
        if pat.match(h):
            return urljoin(BASE, h)
    return None


def _extract_set_urls(hrefs: list[str], year: int) -> list[str]:
    # ex: /pop/baseball-cards/1991/stadium-club/46514
    pat = re.compile(rf"^/pop/[^/]+/{year}/[^/]+/\d+$")
    out: list[str] = []
    for h in hrefs:
        if pat.match(h):
            out.append(urljoin(BASE, h))

    # de-dupe preserve order
    seen = set()
    dedup: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup


def _load_sets(sport: str, year: int, *, headless: bool, timeout_s: int) -> list[PopSet]:
    slug, cat_id = SPORT_TO_CATEGORY[sport]
    category_root = f"{BASE}/pop/{slug}/{cat_id}"
    year_link_pat = rf"/pop/{slug}/{year}/\d+"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=headless,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        # 1) Category page
        page.goto(category_root, wait_until="domcontentloaded", timeout=timeout_s * 1000)

        # Wait until the specific year link exists (avoids CF/partial-load)
        try:
            page.wait_for_function(
                """(pattern) => Array.from(document.querySelectorAll('a[href]'))
                    .some(a => new RegExp(pattern).test(a.getAttribute('href') || ''))""",
                arg=year_link_pat,
                timeout=timeout_s * 1000,
            )
        except PlaywrightTimeoutError:
            ctx.close()
            return []

        hrefs = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
        )
        year_url = _extract_year_url(hrefs, year)
        if not year_url:
            ctx.close()
            return []

        # 2) Year page (lists sets)
        page.goto(year_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        page.wait_for_selector("a[href]", timeout=timeout_s * 1000)

        anchors = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({href: e.getAttribute('href'), text: (e.textContent||'').trim()}))",
        )

        href_to_text: Dict[str, str] = {}
        href_list: list[str] = []
        for a in anchors:
            h = a.get("href") or ""
            t = a.get("text") or ""
            if h:
                href_list.append(h)
                if t:
                    href_to_text[urljoin(BASE, h)] = t

        set_urls = _extract_set_urls(href_list, year)
        sets: list[PopSet] = []
        for u in set_urls:
            name = href_to_text.get(u, "")
            if name:
                sets.append(PopSet(name=name, url=u))

        ctx.close()

    sets.sort(key=lambda s: s.name.lower())
    return sets


def list_sets_for_sport_year(sport: str, year: int, *, headless: bool = True, timeout_s: int = 90) -> list[PopSet]:
    """
    Returns all PSA Pop sets for a given sport + year.

    Uses a persistent Playwright profile so Cloudflare clearance persists across runs.
    Tries headless first; if blocked, retries headful so you can complete the challenge once.
    """
    if sport not in SPORT_TO_CATEGORY:
        raise ValueError(f"Unsupported sport: {sport}")

    sets = _load_sets(sport, year, headless=headless, timeout_s=timeout_s)
    if sets:
        return sets

    # Headful fallback (most reliable if Cloudflare blocks headless)
    print("\n⚠️ If a browser window opens with 'Just a moment…', complete the challenge once.")
    return _load_sets(sport, year, headless=False, timeout_s=timeout_s)