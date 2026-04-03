from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

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


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


async def _post_from_page(
    page,
    *,
    set_id: int,
    category_id: str,
    draw: int,
    start: int,
) -> Dict[str, Any]:
    payload = {
        "headingID": str(set_id),
        "categoryID": str(category_id),
        "draw": str(draw),
        "start": str(start),
        "length": str(PAGE_SIZE),
        "isPSADNA": "false",
    }

    result = await page.evaluate(
        """
        async ({ url, payload }) => {
          const resp = await fetch(url, {
            method: "POST",
            credentials: "include",
            headers: {
              "Accept": "application/json, text/plain, */*",
              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
              "X-Requested-With": "XMLHttpRequest"
            },
            body: new URLSearchParams(payload).toString()
          });

          const text = await resp.text();
          return {
            status: resp.status,
            contentType: resp.headers.get("content-type") || "",
            text
          };
        }
        """,
        {"url": GET_SET_ITEMS_URL, "payload": payload},
    )

    return result


async def _fetch_rows(pop_set_url: str, timeout_s: int) -> List[Dict[str, Any]]:
    set_id = _extract_set_id(pop_set_url)
    category_id = _extract_category_id(pop_set_url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            });
            """
        )

        await page.goto(pop_set_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)

        print("\\nA browser window opened.")
        print("If PSA shows a cookie banner, accept it.")
        print("If the page looks loaded, come back here and press Enter.")
        input("Press Enter to continue... ")

        all_rows: List[Dict[str, Any]] = []
        start = 0
        draw = 1

        while True:
            result = await _post_from_page(
                page,
                set_id=set_id,
                category_id=category_id,
                draw=draw,
                start=start,
            )

            status = int(result.get("status", 0))
            text = result.get("text") or ""
            content_type = (result.get("contentType") or "").lower()

            if status != 200:
                await browser.close()
                raise RuntimeError(f"PSA returned {status}")

            if "json" not in content_type and not text.lstrip().startswith("{"):
                snippet = text[:300].replace("\\n", " ")
                await browser.close()
                raise RuntimeError(f"PSA returned non-JSON response: {snippet}")

            data = json.loads(text)
            rows = data.get("data", []) or []
            all_rows.extend(rows)

            try:
                records_total = int(data.get("recordsTotal", len(all_rows)) or len(all_rows))
            except Exception:
                records_total = len(all_rows)

            if not rows or len(all_rows) >= records_total:
                break

            start += PAGE_SIZE
            draw += 1

        await browser.close()
        return all_rows


def fetch_set_population_rows(
    pop_set_url: str,
    *,
    timeout_s: int = 45,
    headless: bool = True,
) -> List[Dict[str, Any]]:
    return asyncio.run(_fetch_rows(pop_set_url, timeout_s))


def filter_card_rows(rows: List[Dict[str, Any]], q: PopQuery) -> List[Dict[str, Any]]:
    if not rows:
        return []

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
        try:
            return int(r.get(k) or 0)
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