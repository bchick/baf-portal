"""Licence filters applied to every aggregator input.

COSMIC, OncoKB, GENIE, OMIM, HGMD, REVEL and CADD content must never be
bundled. Aggregators such as the EBI Proteins /variation endpoint or
myvariant.info mix COSMIC rows in; they are dropped here.
"""
from __future__ import annotations

import json

BLOCKED = ("cosmic", "oncokb", "genie", "hgmd", "revel", "cadd")


def is_blocked(row) -> bool:
    blob = json.dumps(row, default=str).lower()
    return any(b in blob for b in BLOCKED)


def drop_blocked(rows: list) -> list:
    return [r for r in rows if not is_blocked(r)]


def strip_omim(conditions: list[dict]) -> list[dict]:
    """Keep condition names and open identifiers only (no OMIM content)."""
    return [{k: v for k, v in c.items() if k != "omim"} for c in conditions]
