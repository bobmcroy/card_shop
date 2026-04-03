from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def safe_filename(value: str | None, fallback: str = "x") -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or fallback


def ensure_parent_dir(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _collect_fieldnames(
    rows: Sequence[Mapping[str, Any]],
    field_order: Sequence[str] | None = None,
) -> list[str]:
    if field_order:
        return list(field_order)

    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                ordered.append(str(key))
    return ordered


def write_rows_to_csv(
    rows: Iterable[Mapping[str, Any]],
    out_path: str | Path,
    field_order: Sequence[str] | None = None,
) -> Path:
    materialized = list(rows)
    out_file = ensure_parent_dir(out_path)

    if not materialized:
        fieldnames = list(field_order or [])
        with out_file.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if fieldnames:
                writer.writeheader()
        return out_file

    fieldnames = _collect_fieldnames(materialized, field_order)

    with out_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow(dict(row))

    return out_file


def write_json(
    data: Any,
    out_path: str | Path,
    *,
    indent: int = 2,
    sort_keys: bool = False,
) -> Path:
    out_file = ensure_parent_dir(out_path)
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, sort_keys=sort_keys, ensure_ascii=False)
        f.write("\n")
    return out_file


def build_output_path(
    out_dir: str | Path,
    *parts: str | int | None,
    ext: str,
) -> Path:
    clean_parts = [safe_filename(str(p)) for p in parts if p is not None and str(p).strip()]
    filename = "_".join(clean_parts) if clean_parts else "output"
    if not ext.startswith("."):
        ext = f".{ext}"
    return Path(out_dir) / f"{filename}{ext}"