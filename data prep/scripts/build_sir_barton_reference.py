#!/usr/bin/env python3
"""Build ``sir_barton_stakes_results_2017_2025.csv`` from HRN finish order (+ scratch notes)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from derby_reference import normalize_horse_name_key

# (year, race_date, race_number, [(horse_name, finish_position), ...])
# Finish order from Horse Racing Nation race pages (user-provided URLs).
# Horse names aligned to Brisnet DRF spellings where they differ (e.g. V. I. P. TICKET).
SIR_BARTON_RESULTS: list[tuple[int, str, int, list[tuple[str, int]]]] = [
    (
        2017,
        "2017-05-20",
        11,
        [
            ("No Mo Dough", 1),
            ("Time To Travel", 2),
            ("True Timber", 3),
            ("Honor The Fleet", 4),
            ("Society Beau", 5),
            ("Hedge Fund", 6),
            ("Greek Prince", 7),
            ("Watch Me Whip", 8),
            ("Resiliency", 9),
        ],
    ),
    (
        2018,
        "2018-05-19",
        12,
        [
            ("Ax Man", 1),
            ("Title Ready", 2),
            ("Prince Lucky", 3),
            ("Pony Up", 4),
            ("Dream Baby Dream", 5),
            ("Navy Commander", 6),
        ],
    ),
    (
        2019,
        "2019-05-18",
        3,
        [
            ("King for a Day", 1),
            ("Tone Broke", 2),
            ("V. I. P. TICKET", 3),
            ("Trifor Gold", 4),
            ("Top Line Growth", 5),
        ],
    ),
    (
        2021,
        "2021-05-15",
        1,
        [
            ("The King Cheek", 1),
            ("Hozier", 2),
            ("Romp", 3),
            ("Golden Gulley", 4),
            ("Market Cap", 5),
        ],
    ),
    (
        2022,
        "2022-05-21",
        11,
        [
            ("Ethereal Road", 1),
            ("B Dawk", 2),
            ("Mr Jefferson", 3),
            ("Ruggs", 4),
            ("Good Skate", 5),
            ("Unikee", 6),
            ("Goldenize", 7),
            ("Writeitontheice", 8),
        ],
    ),
    (
        2023,
        "2023-05-20",
        4,
        [
            ("Arabian Lion", 1),
            ("Tapit's Conquest", 2),
            ("Denington", 3),
            ("Sheriff Ronnie", 4),
            ("Feeling Woozy", 5),
        ],
    ),
    (
        2024,
        "2024-05-18",
        10,
        [
            ("Corporate Power", 1),
            ("Gould's Gold", 2),
            ("Imperial Gun", 3),
            ("Real Macho", 4),
            ("Daily Grind", 5),
            ("D Day Sky", 6),
            ("Circle P", 7),
            ("Deposition", 8),
        ],
    ),
    (
        2025,
        "2025-05-17",
        10,
        [
            ("Crudo", 1),
            ("Just a Fair Shake", 2),
            ("Invictus", 3),
            ("Bear Claw Necklace", 4),
            ("Authentic Gallop", 5),
            ("Bestfriend Rocket", 6),
            ("Bold Diversion", 7),
        ],
    ),
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "reference" / "sir_barton_stakes_results_2017_2025.csv"
    rows: list[dict[str, str | int]] = []
    for year, race_date, race_num, finishers in SIR_BARTON_RESULTS:
        for horse_name, finish in finishers:
            rows.append(
                {
                    "year": year,
                    "race_date": race_date,
                    "track_code": "PIM",
                    "race_number": race_num,
                    "horse_name": horse_name,
                    "horse_name_key": normalize_horse_name_key(horse_name).lower(),
                    "finish_position": finish,
                    "finish_status": "",
                }
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "year",
        "race_date",
        "track_code",
        "race_number",
        "horse_name",
        "horse_name_key",
        "finish_position",
        "finish_status",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
