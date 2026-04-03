# utils/pretty_table.py
from __future__ import annotations

from typing import Any, Dict, List, Optional


def print_aligned_table(rows: List[Dict[str, Any]], columns: List[str], max_width: int = 40) -> None:
    if not rows:
        print("(no rows)")
        return

    def cell(v: Any) -> str:
        s = "" if v is None else str(v)
        s = s.replace("\n", " ").strip()
        if len(s) > max_width:
            return s[: max_width - 1] + "…"
        return s

    # compute widths
    widths = {c: len(c) for c in columns}
    for r in rows:
        for c in columns:
            widths[c] = max(widths[c], len(cell(r.get(c))))

    # header
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)

    # rows
    for r in rows:
        line = "  ".join(cell(r.get(c)).ljust(widths[c]) for c in columns)
        print(line)