"""Parse Brisnet single-file results (``.RES``) into tabular finish data."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from derby_reference import normalize_horse_name_key

# Brisnet .RES row layout (0-based); verified against Pimlico Preakness-week cards.
_RES_TRACK = 0
_RES_CARD_DATE = 1
_RES_RACE = 2
_RES_DISTANCE = 3
_RES_SURFACE = 4
_RES_RACE_NAME = 12
_RES_POST = 13
_RES_HORSE = 15
_RES_FINISH = 19
_RES_FINAL_ODDS = 21

_DRF_RES_STEM_RE = re.compile(r"^(.+)\.(?:DRF|drf)$", re.IGNORECASE)


def results_path_for_drf(drf_path: str | Path, results_dir: str | Path) -> Path | None:
    """Map ``PIM0515-2021.DRF`` → ``results/PIM0515-2021.RES`` when that file exists."""
    drf_path = Path(drf_path)
    m = _DRF_RES_STEM_RE.match(drf_path.name)
    if not m:
        return None
    candidate = Path(results_dir) / f"{m.group(1)}.RES"
    return candidate if candidate.is_file() else None


def load_results_file(path: str | Path) -> pd.DataFrame:
    """Load one ``.RES`` file into a normalized results frame."""
    path = Path(path)
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            fields = next(csv.reader([line]))
            if len(fields) <= _RES_FINAL_ODDS:
                continue
            finish_raw = fields[_RES_FINISH].strip()
            if not finish_raw or not finish_raw.isdigit():
                continue
            finish = int(finish_raw)
            if finish <= 0 or finish >= 90:
                continue

            odds_raw = fields[_RES_FINAL_ODDS].strip()
            odds = float(odds_raw) if odds_raw else pd.NA

            card_date = fields[_RES_CARD_DATE].strip()
            horse = fields[_RES_HORSE].strip()
            rows.append(
                {
                    "track": fields[_RES_TRACK].strip(),
                    "card_date": card_date,
                    "race": int(fields[_RES_RACE]),
                    "distance": fields[_RES_DISTANCE].strip(),
                    "surface": fields[_RES_SURFACE].strip(),
                    "race_name": fields[_RES_RACE_NAME].strip(),
                    "post_position": int(fields[_RES_POST]),
                    "horse_name": horse,
                    "horse_name_key": normalize_horse_name_key(horse),
                    "official_finish_position": finish,
                    "official_final_odds": odds,
                    "_source_res": path.name,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "track",
                "card_date",
                "race",
                "distance",
                "surface",
                "race_name",
                "post_position",
                "horse_name",
                "horse_name_key",
                "official_finish_position",
                "official_final_odds",
                "_source_res",
            ]
        )

    out = pd.DataFrame(rows)
    out["card_date"] = pd.to_datetime(out["card_date"], format="%Y%m%d", errors="coerce")
    return out


def load_results_directory(results_dir: str | Path) -> pd.DataFrame:
    """Load and concatenate every ``*.RES`` under *results_dir*."""
    results_dir = Path(results_dir)
    if not results_dir.is_dir():
        return pd.DataFrame()

    chunks: list[pd.DataFrame] = []
    for path in sorted(results_dir.glob("*.RES")):
        chunks.append(load_results_file(path))
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)
