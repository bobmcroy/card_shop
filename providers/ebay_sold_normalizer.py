from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


MONEY_RE = re.compile(r"\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)")
GRADE_RE = re.compile(r"\b(10|9(?:\.[0-9])?|8(?:\.[0-9])?|7(?:\.[0-9])?|6(?:\.[0-9])?|5(?:\.[0-9])?|4(?:\.[0-9])?|3(?:\.[0-9])?|2(?:\.[0-9])?|1(?:\.[0-9])?)\b")

CARD_NUMBER_PATTERNS = [
    re.compile(r"(?:^|\s)#\s*([A-Z]?\d+[A-Z]?)\b", re.IGNORECASE),
    re.compile(r"\b(?:no\.?|number)\s*([A-Z]?\d+[A-Z]?)\b", re.IGNORECASE),
    re.compile(r"\bcard\s*#?\s*([A-Z]?\d+[A-Z]?)\b", re.IGNORECASE),
    re.compile(r"\b([A-Z]?\d+[A-Z]?)\s*/\s*\d+\b", re.IGNORECASE),
]

STANDALONE_CARD_NUMBER_RE = re.compile(r"\b([A-Z]?\d{1,4}[A-Z]?)\b", re.IGNORECASE)

EXCLUDED_CARD_NUMBER_TOKENS = {
    "1989", "1990", "1991", "1992", "1993", "1994", "1995", "1996",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
}


def parse_money(value: str | None) -> Optional[float]:
    if not value:
        return None

    text = value.strip().lower()
    if "free" in text:
        return 0.0

    match = MONEY_RE.search(text.replace(",", ""))
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_sold_date(value: str | None) -> Optional[str]:
    if not value:
        return None

    text = value.strip()
    text = re.sub(r"^\s*Sold\s*", "", text, flags=re.IGNORECASE).strip()

    date_formats = [
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%y",
        "%m/%d/%Y",
    ]

    for fmt in date_formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass

    return None


def normalize_grader(value: str | None, title: str | None = None) -> Optional[str]:
    text = " ".join(filter(None, [value, title])).upper()

    if "PSA" in text:
        return "PSA"
    if "BGS" in text or "BECKETT" in text:
        return "BGS"
    if "SGC" in text:
        return "SGC"
    if "CGC" in text:
        return "CGC"
    if "CSG" in text:
        return "CSG"
    if "TAG" in text:
        return "TAG"

    return None


def parse_grade_value(grade: str | None, title: str | None = None) -> Optional[float]:
    for source in [grade, title]:
        if not source:
            continue
        match = GRADE_RE.search(source)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def detect_is_graded(graded: Any, grader: str | None, grade: str | None, title: str | None) -> bool:
    if isinstance(graded, bool):
        return graded
    if isinstance(graded, str) and graded.strip().lower() in {"true", "yes", "1", "y"}:
        return True
    if grader or grade:
        return True

    title_text = (title or "").upper()
    graded_terms = ["PSA", "BGS", "SGC", "CGC", "CSG", "TAG", "GEM MT", "MINT 9", "10"]
    return any(term in title_text for term in graded_terms)


def detect_listing_type(row: Dict[str, Any]) -> str:
    auction = str(row.get("auction", "")).strip().lower()
    best_offer = str(row.get("best_offer", "")).strip().lower()
    title = str(row.get("title", "")).strip().lower()

    if auction in {"true", "yes", "1", "y"}:
        return "auction"

    if best_offer in {"true", "yes", "1", "y"}:
        return "bin"

    if "auction" in title:
        return "auction"

    return "bin"


def detect_best_offer(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def extract_card_number_guess(title: str | None) -> Optional[str]:
    text = (title or "").strip()
    if not text:
        return None

    for pat in CARD_NUMBER_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip().upper().replace(" ", "")
            if candidate and candidate not in EXCLUDED_CARD_NUMBER_TOKENS:
                return candidate

    for m in STANDALONE_CARD_NUMBER_RE.finditer(text):
        candidate = m.group(1).strip().upper().replace(" ", "")
        if not candidate:
            continue
        if candidate in EXCLUDED_CARD_NUMBER_TOKENS:
            continue
        if re.fullmatch(r"\d{4}", candidate):
            continue
        return candidate

    return None


def safe_round(value: Optional[float]) -> Optional[float]:
    if value is None or math.isnan(value):
        return None
    return round(value, 2)


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    title = row.get("title")
    price = row.get("price")
    shipping = row.get("shipping")
    sold_date = row.get("sold_date")
    grader = row.get("grader")
    grade = row.get("grade")
    graded = row.get("graded")
    best_offer = row.get("best_offer")

    price_value = parse_money(price)
    shipping_value = parse_money(shipping)
    total_value = None
    if price_value is not None:
        total_value = price_value + (shipping_value or 0.0)

    grader_norm = normalize_grader(grader, title)
    grade_value = parse_grade_value(grade, title)
    is_graded = detect_is_graded(graded, grader, grade, title)
    is_best_offer = detect_best_offer(best_offer)
    listing_type = detect_listing_type(row)
    sold_date_value = parse_sold_date(sold_date)
    card_number_guess = extract_card_number_guess(title)

    normalized = dict(row)
    normalized.update(
        {
            "price_value": safe_round(price_value),
            "shipping_value": safe_round(shipping_value),
            "total_value": safe_round(total_value),
            "sold_date_value": sold_date_value,
            "listing_type": listing_type,
            "is_best_offer": is_best_offer,
            "is_graded": is_graded,
            "grader_norm": grader_norm,
            "grade_value": grade_value,
            "card_number_guess": card_number_guess,
        }
    )
    return normalized


def normalize_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_row(row) for row in rows]