from __future__ import annotations

import re
import time
import cloudscraper
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

GET_SET_ITEMS_URL = "https://www.psacard.com/Pop/GetSetItems"
PAGE_SIZE = 300

CATEGORY_ID_BY_SLUG = {
    "baseball-cards": "20003",
    "basketball-cards": "20009",
    "football-cards": "20014",
    "hockey-cards": "20012",
    "tcg-cards": "20025",
    "soccer-cards": "20023",
    "non-sport-cards": "20032",
    "multi-sport-cards": "20029",
}


@dataclass
class PopQuery:
    pop_set_url: str
    player: str
    card_number: Optional[str] = None
    variety_contains: Optional[str] = None


def _extract_set_id(pop_set_url: str) -> int:
    return int(pop_set_url.rstrip("/").split("/")[-1])


def _extract_category_id(pop_set_url: str) -> str:
    parts = pop_set_url.split("/")
    try:
        idx = parts.index("pop")
        slug = parts[idx + 1]
        return CATEGORY_ID_BY_SLUG.get(slug, "20019")
    except Exception:
        return "20019"


def fetch_set_population_rows(pop_set_url: str, *, timeout_s: int = 30) -> List[Dict[str, Any]]:
    set_id = _extract_set_id(pop_set_url)
    category_id = _extract_category_id(pop_set_url)

    sess = cloudscraper.create_scraper(
        browser={
            "browser": "chrome",
            "platform": "darwin",
            "mobile": False,
        }
    )

    # 1) Prime cookies / session by loading the actual Pop set page first
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    sess.get(pop_set_url, timeout=timeout_s)

    # 2) Now do the XHR-style POST the page normally does
    xhr_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://www.psacard.com",
        "Referer": pop_set_url,
        "X-Requested-With": "XMLHttpRequest",
    }

    start = 0
    draw = 1
    all_rows: List[Dict[str, Any]] = []

    while True:
        form_data = {
            "headingID": str(set_id),
            "categoryID": str(category_id),
            "draw": draw,
            "start": start,
            "length": PAGE_SIZE,
            "isPSADNA": "false",
        }

        resp = sess.post(GET_SET_ITEMS_URL, data=form_data, headers=xhr_headers, timeout=timeout_s)

        # Helpful debug if it fails again
        if resp.status_code == 403:
            raise RuntimeError(
                f"403 Forbidden from PSA Pop endpoint. "
                f"Try cloudscraper/Playwright fallback. Response snippet: {resp.text[:200]}"
            )

        resp.raise_for_status()
        payload = resp.json()

        rows = payload.get("data", []) or []
        all_rows.extend(rows)

        records_total = int(payload.get("recordsTotal", len(all_rows)) or len(all_rows))
        start += PAGE_SIZE
        draw += 1

        if len(all_rows) >= records_total:
            break

        time.sleep(0.25)

    return all_rows


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def filter_card_rows(rows: List[Dict[str, Any]], q: PopQuery) -> List[Dict[str, Any]]:
    player_n = _norm(q.player)
    cn_n = _norm(q.card_number or "")
    var_n = _norm(q.variety_contains or "")

    out = []
    for r in rows:
        name = _norm(str(r.get("SubjectName", "")))
        card_no = _norm(str(r.get("CardNumber", "")))
        variety = _norm(str(r.get("Variety", "")))

        if player_n and player_n not in name:
            continue
        if cn_n and cn_n != card_no:
            continue
        if var_n and var_n not in variety:
            continue
        out.append(r)

    return out


def pop_row_to_scarcity_summary(r: Dict[str, Any]) -> Dict[str, Any]:
    def g(k: str) -> int:
        v = r.get(k)
        try:
            return int(v) if v is not None and str(v).strip() != "" else 0
        except Exception:
            return 0

    total = g("Total") or g("GradeTotal") or 0

    return {
        "spec_id": r.get("SpecID"),
        "player": r.get("SubjectName"),
        "card_number": r.get("CardNumber"),
        "variety": r.get("Variety"),
        "total_pop": total,
        "pop_10": g("Grade10"),
        "pop_9": g("Grade9"),
        "pop_8": g("Grade8"),
        "pop_7": g("Grade7"),
        "pop_6": g("Grade6"),
        "pop_5": g("Grade5"),
        "pop_4": g("Grade4"),
        "pop_3": g("Grade3"),
        "pop_2": g("Grade2"),
        "pop_1": g("Grade1"),
    }