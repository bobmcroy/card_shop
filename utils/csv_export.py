# utils/csv_export.py
from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional


def write_rows_to_csv(
    rows: List[Dict[str, Any]],
    out_path: str,
    field_order: Optional[List[str]] = None,
) -> None:
    # Determine headers in a stable way
    if field_order:
        # include ordered fields first, then any extra keys discovered
        extras = []
        seen = set(field_order)
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    extras.append(k)
                    seen.add(k)
        fieldnames = list(field_order) + extras
    else:
        fieldnames = []
        seen = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    seen.add(k)
                    fieldnames.append(k)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)