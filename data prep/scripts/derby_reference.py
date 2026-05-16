"""Join official Kentucky Derby results (finish, odds) onto Brisnet DRF frames."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,4}\)\s*$")


def normalize_horse_name_key(name: str | float | None) -> str:
    """Uppercase, strip, and remove trailing ``(JPN)``-style country codes for matching."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).strip().upper()
    s = _COUNTRY_SUFFIX_RE.sub("", s)
    return s.strip()


def load_derby_results_table(path: str | Path) -> pd.DataFrame:
    """Load ``kentucky_derby_results_*.csv`` into a merge-ready table keyed by year + name."""
    ref = pd.read_csv(path)
    ref = ref.rename(
        columns={
            "finish_position": "official_finish_position",
            "final_odds": "official_final_odds",
        }
    )
    ref["horse_name_key"] = ref["horse_name"].map(normalize_horse_name_key)
    ref = ref.rename(columns={"year": "race_year"})
    return ref[
        ["race_year", "horse_name_key", "official_finish_position", "official_final_odds"]
    ].drop_duplicates(subset=["race_year", "horse_name_key"])


def merge_official_derby_results(
    df: pd.DataFrame,
    reference: Path | pd.DataFrame,
    *,
    copy: bool = True,
) -> pd.DataFrame:
    """Attach ``official_finish_position`` and ``official_final_odds`` for Kentucky Derby rows.

    Uses ``todays_race_classification`` containing ``KyDerby`` and matches reference
    rows on ``race_year`` (from ``date``) and normalized horse name. Non-Derby rows
    get NA in the official columns.
    """
    if isinstance(reference, (str, Path)):
        ref = load_derby_results_table(Path(reference))
    else:
        ref = reference[
            ["race_year", "horse_name_key", "official_finish_position", "official_final_odds"]
        ].drop_duplicates(subset=["race_year", "horse_name_key"])

    out = df.copy() if copy else df

    if "date" not in out.columns or "horse_name" not in out.columns:
        raise KeyError("DataFrame must include 'date' and 'horse_name'")
    if "todays_race_classification" not in out.columns:
        raise KeyError("DataFrame must include 'todays_race_classification'")

    out["horse_name_key"] = out["horse_name"].map(normalize_horse_name_key)
    out["race_year"] = pd.to_datetime(out["date"]).dt.year

    derby_mask = out["todays_race_classification"].str.contains("KyDerby", na=False)

    if not derby_mask.any():
        out = out.drop(columns=["horse_name_key", "race_year"])
        return out

    # Merge before attaching official_* to the full frame so column names do not collide.
    derby_joined = out.loc[derby_mask].merge(
        ref,
        on=["race_year", "horse_name_key"],
        how="left",
    )
    if len(derby_joined) != derby_mask.sum():
        raise RuntimeError("merge row count mismatch")

    out["official_finish_position"] = pd.NA
    out["official_final_odds"] = pd.NA
    out.loc[derby_mask, "official_finish_position"] = derby_joined[
        "official_finish_position"
    ].values
    out.loc[derby_mask, "official_final_odds"] = derby_joined["official_final_odds"].values

    out = out.drop(columns=["horse_name_key", "race_year"])
    return out


def finalize_derby_training_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``year``, rename finish to ``target_FP``, drop rows without numeric finish, add targets.

    Rows with non-numeric finish (missing merge, ``scratched``, etc.) are removed.
    ``target_top3`` / ``target_top5`` are 1 only when ``target_FP`` is in 1–3 / 1–5.
    """
    out = df.copy()
    out["year"] = pd.to_datetime(out["date"], errors="coerce").dt.year

    if "official_finish_position" not in out.columns:
        raise KeyError(
            "Need column official_finish_position (merge reference CSV before finalize)."
        )

    out = out.rename(columns={"official_finish_position": "target_FP"})
    fp_num = pd.to_numeric(out["target_FP"], errors="coerce")
    out = out.assign(_fp=fp_num).dropna(subset=["_fp"])
    out["target_FP"] = out["_fp"].astype(int)
    out = out.drop(columns=["_fp"])

    fp = out["target_FP"]
    out["target_top3"] = fp.between(1, 3, inclusive="both").astype(int)
    out["target_top5"] = fp.between(1, 5, inclusive="both").astype(int)
    return out


def attach_derby_labels_to_pp_long(
    pp_long: pd.DataFrame,
    wide_labeled: pd.DataFrame,
) -> pd.DataFrame:
    """Copy training labels from the wide Derby frame onto PP-long rows."""
    key_cols = ["track", "date", "race", "horse_name"]
    for c in key_cols:
        if c not in pp_long.columns or c not in wide_labeled.columns:
            raise KeyError(f"Both frames must include {key_cols!r}")

    extra = [
        c
        for c in (
            "target_FP",
            "official_final_odds",
            "year",
            "target_top3",
            "target_top5",
            "target_ml_rank_minus_finish",
            "target_top5_ml_rank_gt4",
            "target_deep_closer_top5",
        )
        if c in wide_labeled.columns
    ]
    if not extra:
        raise KeyError("Wide frame has no label columns to attach.")
    lookup = wide_labeled[key_cols + extra].drop_duplicates(subset=key_cols)
    return pp_long.merge(lookup, on=key_cols, how="left")


def attach_official_to_pp_long(
    pp_long: pd.DataFrame,
    wide_with_official: pd.DataFrame,
) -> pd.DataFrame:
    """Deprecated alias for :func:`attach_derby_labels_to_pp_long`."""
    return attach_derby_labels_to_pp_long(pp_long, wide_with_official)
