from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_CARD_NUMBER_REGEXES = [
    re.compile(r"#\s*([A-Za-z0-9-]+)\b"),
    re.compile(r"\bNo\.?\s*([A-Za-z0-9-]+)\b", re.I),
]

_GRADER_ORDER = {"PSA": 0, "BGS": 1, "SGC": 2, "CGC": 3, "CSG": 4}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_lower(value: Any) -> str:
    return _norm(value).lower()


def _parse_money(value: Any) -> float | None:
    text = _norm(value)
    if not text:
        return None
    text = text.replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_sold_date(value: Any) -> str:
    text = _norm(value)
    if not text:
        return ""
    text = re.sub(r"^Sold\s+", "", text, flags=re.I)
    for fmt in ["%b %d, %Y", "%B %d, %Y"]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _parse_bool_from_flag(value: Any) -> bool:
    return _safe_lower(value) in {"y", "yes", "true", "1"}


def _normalize_grader(value: Any) -> str:
    return _norm(value).upper()


def _grade_value(value: Any) -> float | None:
    text = _norm(value).upper()
    if not text:
        return None
    if text == "AUTH":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _guess_card_number(title: Any) -> str:
    text = _norm(title)
    if not text:
        return ""
    for rx in _CARD_NUMBER_REGEXES:
        m = rx.search(text)
        if m:
            return _norm(m.group(1)).upper()
    return ""


def _listing_type(row: dict[str, Any]) -> str:
    explicit = _norm(row.get("listing_type"))
    if explicit:
        return explicit
    if _parse_bool_from_flag(row.get("auction")):
        return "auction"
    return "buy_now"


def _condition(row: dict[str, Any]) -> str:
    condition = _norm(row.get("condition"))
    if condition:
        return condition
    if _parse_bool_from_flag(row.get("graded")):
        return "Graded"
    return ""


def _sort_key(row: dict[str, Any]) -> tuple:
    grader = _normalize_grader(row.get("grader"))
    grade_value = _grade_value(row.get("grade"))
    sold_date = _parse_sold_date(row.get("sold_date"))
    title = _norm(row.get("title"))
    return (
        sold_date or "9999-99-99",
        _GRADER_ORDER.get(grader, 99),
        -(grade_value if grade_value is not None else -1),
        title,
    )


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for raw in rows:
        title = _norm(raw.get("title"))
        price = _norm(raw.get("price"))
        shipping = _norm(raw.get("shipping")) or "$0.00"
        sold_date = _norm(raw.get("sold_date"))
        seller = _norm(raw.get("seller"))
        condition = _condition(raw)
        item_url = _norm(raw.get("item_url"))
        image_url = _norm(raw.get("image_url"))
        graded = _parse_bool_from_flag(raw.get("graded"))
        grader = _normalize_grader(raw.get("grader"))
        grade = _norm(raw.get("grade"))
        auction = _parse_bool_from_flag(raw.get("auction"))
        best_offer = _parse_bool_from_flag(raw.get("best_offer"))
        price_value = _parse_money(price)
        shipping_value = _parse_money(shipping)
        total_value = None
        if price_value is not None:
            total_value = price_value + (shipping_value or 0.0)

        normalized.append(
            {
                "title": title,
                "price": price,
                "shipping": shipping,
                "sold_date": sold_date,
                "seller": seller,
                "condition": condition,
                "item_url": item_url,
                "image_url": image_url,
                "graded": "Y" if graded else "N",
                "grader": grader,
                "grade": grade,
                "auction": "Y" if auction else "N",
                "best_offer": "Y" if best_offer else "N",
                "price_value": price_value,
                "shipping_value": shipping_value,
                "total_value": total_value,
                "sold_date_value": _parse_sold_date(sold_date),
                "listing_type": _listing_type(raw),
                "is_best_offer": best_offer,
                "is_graded": graded,
                "grader_norm": grader,
                "grade_value": _grade_value(grade),
                "card_number_guess": _guess_card_number(title),
                "source_market": _norm(raw.get("source_market")) or "fanatics",
                "item_id": _norm(raw.get("item_id")),
                "sales_history_url": _norm(raw.get("sales_history_url")) or item_url,
                "guide_price": _norm(raw.get("guide_price")),
                "sale_event": _norm(raw.get("sale_event")),
                "sale_row_label": _norm(raw.get("sale_row_label")),
                "currency": _norm(raw.get("currency")) or "USD",
            }
        )

    return sorted(normalized, key=_sort_key)
