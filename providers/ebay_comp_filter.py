from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CompFilterCriteria:
    sport: str
    year: int
    set_name: str
    player_name: Optional[str] = None
    card_number: Optional[str] = None
    grader: Optional[str] = None
    grade_value: Optional[float] = None
    require_graded: Optional[bool] = None


# obvious junk listings that should never count as comps
JUNK_PATTERNS = [
    r"\blot\b",
    r"\blots\b",
    r"\bset break\b",
    r"\bcomplete set\b",
    r"\bteam set\b",
    r"\breprint\b",
    r"\brp\b",
    r"\bproxy\b",
    r"\bcustom\b",
    r"\bfacsimile\b",
    r"\bunopened\b",
    r"\bbox\b",
    r"\bpack\b",
    r"\bcase\b",
]


JUNK_REGEX = re.compile("|".join(JUNK_PATTERNS), re.I)


def _title(row: dict) -> str:
    return (row.get("title") or "").lower()


def _reject_junk(row: dict) -> bool:
    title = _title(row)
    return bool(JUNK_REGEX.search(title))


def _match_player(row: dict, player_name: str) -> bool:
    if not player_name:
        return True

    title = _title(row)
    tokens = player_name.lower().split()

    return all(token in title for token in tokens)


def _match_card_number(row: dict, card_number: str) -> bool:
    if not card_number:
        return True

    wanted = card_number.replace("#", "").strip().upper()

    guessed = (row.get("card_number_guess") or "").strip().upper()
    if guessed:
        return guessed == wanted

    title = _title(row)
    return f"#{wanted.lower()}" in title or f" {wanted.lower()} " in title


def _match_grader(row: dict, grader: str) -> bool:
    if not grader:
        return True

    return (row.get("grader_norm") or "").upper() == grader.upper()


def _match_grade_value(row: dict, grade_value: float) -> bool:
    if grade_value is None:
        return True

    val = row.get("grade_value")

    try:
        return float(val) == float(grade_value)
    except Exception:
        return False


def _match_graded_requirement(row: dict, require_graded: Optional[bool]) -> bool:
    if require_graded is None:
        return True

    return bool(row.get("is_graded")) == require_graded


def filter_comps(
    rows: List[dict],
    criteria: CompFilterCriteria,
) -> List[dict]:

    filtered: List[dict] = []

    for row in rows:

        if _reject_junk(row):
            continue

        if not _match_player(row, criteria.player_name):
            continue

        if not _match_card_number(row, criteria.card_number):
            continue

        if not _match_grader(row, criteria.grader):
            continue

        if not _match_grade_value(row, criteria.grade_value):
            continue

        if not _match_graded_requirement(row, criteria.require_graded):
            continue

        filtered.append(row)

    return filtered