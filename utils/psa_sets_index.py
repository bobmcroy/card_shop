# utils/psa_sets_index.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TypedDict


DEFAULT_INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "psa_sets_index.json")
SPORTS = ["Baseball", "Football", "Basketball", "Hockey"]


@dataclass(frozen=True)
class SetEntry:
    name: str
    url: str


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_index(path: str = DEFAULT_INDEX_PATH) -> dict:
    """
    Loads index in the *new* schema:
      {
        "year_pages": { Sport: { Year: url } },
        "sets": { Sport: { Year: [ {name,url}, ... ] } }
      }
    Returns a dict in that same schema (with defaults if missing).
    """
    if not os.path.exists(path):
        return {"year_pages": {s: {} for s in SPORTS}, "sets": {s: {} for s in SPORTS}}

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Back-compat: if someone still has the OLD schema {Sport:{Year:[...]}}
    if "sets" not in raw and any(k in raw for k in SPORTS):
        return {"year_pages": {s: {} for s in SPORTS}, "sets": raw}

    # Ensure defaults exist
    year_pages = raw.get("year_pages") or {}
    sets = raw.get("sets") or {}

    fixed = {
        "year_pages": {s: dict(year_pages.get(s) or {}) for s in SPORTS},
        "sets": {s: dict(sets.get(s) or {}) for s in SPORTS},
    }
    return fixed


def save_index(index: dict, path: str = DEFAULT_INDEX_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Normalize & sort sets by name for each sport/year
    out = {
        "year_pages": index.get("year_pages", {s: {} for s in SPORTS}),
        "sets": {},
    }

    sets = index.get("sets") or {}
    for sport in SPORTS:
        out["sets"][sport] = {}
        sport_years = sets.get(sport) or {}
        for year, entries in sport_years.items():
            normalized: List[dict] = []
            for e in entries or []:
                if isinstance(e, SetEntry):
                    normalized.append({"name": e.name, "url": e.url})
                elif isinstance(e, dict):
                    normalized.append({"name": e.get("name", ""), "url": e.get("url", "")})
            normalized = [e for e in normalized if e["name"] and e["url"]]
            normalized.sort(key=lambda x: x["name"].lower())
            out["sets"][sport][str(year)] = normalized

    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def get_sets(index: dict, sport: str, year: int) -> List[SetEntry]:
    sets_raw = index.get("sets", {}).get(sport, {}).get(str(year), []) or []
    # sets_raw should be list[dict{name,url}]
    out: List[SetEntry] = []
    for s in sets_raw:
        if isinstance(s, dict) and "name" in s and "url" in s:
            out.append(SetEntry(name=s["name"], url=s["url"]))
    return out


def get_year_page(index: dict, sport: str, year: int) -> Optional[str]:
    return (index.get("year_pages", {}).get(sport, {}) or {}).get(str(year))


def add_set(index: dict, sport: str, year: int, name: str, url: str) -> None:
    sport_map = index.setdefault("sets", {}).setdefault(sport, {})
    year_list = sport_map.setdefault(str(year), [])

    name = name.strip()
    url = url.strip()

    # de-dupe by url
    for existing in year_list:
        if isinstance(existing, dict) and existing.get("url") == url:
            return

    year_list.append({"name": name, "url": url})