"""Join official Pimlico stake finishes from Brisnet ``.RES`` files onto DRF frames."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from brisnet_results import load_results_directory, load_results_file, results_path_for_drf
from derby_reference import normalize_horse_name_key

# Brisnet ``todays_race_classification`` substrings (DRF) ↔ ``race_name`` tokens (RES).
_PREAKNESS_CLASS = "Preaknes"
_SIR_BARTON_CLASS = "SirBarton"
_G1_DIRT_CLASS = "UAEPrsCp"

_PREAKNESS_RES = "Preaknes"
_SIR_BARTON_RES = "SirBarton"
_G1_DIRT_RES = "UAEPrsCp"


def _race_year_series(dates: pd.Series) -> pd.Series:
    return pd.to_datetime(dates, errors="coerce").dt.year


def _filter_res_races(res: pd.DataFrame, race_name_token: str) -> pd.DataFrame:
    if res.empty:
        return res
    mask = res["race_name"].astype(str).str.contains(race_name_token, na=False)
    return res.loc[mask].copy()


def _preakness_results_table(res: pd.DataFrame) -> pd.DataFrame:
    ref = _filter_res_races(res, _PREAKNESS_RES)
    if ref.empty:
        return ref
    ref = ref.rename(columns={"horse_name": "ref_horse_name"})
    ref["race_year"] = ref["card_date"].dt.year
    return ref[
        [
            "race_year",
            "horse_name_key",
            "ref_horse_name",
            "official_finish_position",
            "official_final_odds",
        ]
    ].drop_duplicates(subset=["race_year", "horse_name_key"])


def _sir_barton_results_table(res: pd.DataFrame) -> pd.DataFrame:
    ref = _filter_res_races(res, _SIR_BARTON_RES)
    if ref.empty:
        return ref
    ref = ref.rename(columns={"horse_name": "ref_horse_name"})
    ref["race_year"] = ref["card_date"].dt.year
    return ref[
        [
            "race_year",
            "horse_name_key",
            "ref_horse_name",
            "official_finish_position",
            "official_final_odds",
        ]
    ].drop_duplicates(subset=["race_year", "horse_name_key"])


def _g1_dirt_results_table(res: pd.DataFrame) -> pd.DataFrame:
    """UAE President's Cup (``UAEPrsCp``) when present in TB results; else empty."""
    ref = _filter_res_races(res, _G1_DIRT_RES)
    if ref.empty:
        return ref
    ref = ref.rename(columns={"horse_name": "ref_horse_name"})
    ref["race_year"] = ref["card_date"].dt.year
    ref["post_position"] = ref["post_position"].astype(int)
    return ref[
        [
            "race_year",
            "race",
            "post_position",
            "ref_horse_name",
            "official_finish_position",
            "official_final_odds",
        ]
    ].drop_duplicates(subset=["race_year", "race", "post_position"])


def _card_date_results_table(res: pd.DataFrame) -> pd.DataFrame:
    """Fallback for G1 dirt: match DRF ``race`` number on the same calendar date."""
    if res.empty:
        return res
    ref = res.rename(columns={"horse_name": "ref_horse_name"}).copy()
    ref["race_year"] = ref["card_date"].dt.year
    ref["post_position"] = ref["post_position"].astype(int)
    ref["race"] = ref["race"].astype(int)
    return ref[
        [
            "card_date",
            "race",
            "post_position",
            "ref_horse_name",
            "official_finish_position",
            "official_final_odds",
        ]
    ].drop_duplicates(subset=["card_date", "race", "post_position"])


def merge_official_pim_results(
    df: pd.DataFrame,
    results: Path | pd.DataFrame,
    *,
    copy: bool = True,
    warn_name_mismatches: bool = True,
    warn_unmatched_sir_barton: bool = False,
) -> pd.DataFrame:
    """Attach ``official_finish_position`` / ``official_final_odds`` for Preakness-week stakes.

    Uses Brisnet ``.RES`` rows keyed by stake:

    - **Preakness** (``Preaknes``): ``race_year`` + normalized ``horse_name`` (posts can shift)
    - **Sir Barton** (``SirBarton``): ``race_year`` + normalized ``horse_name``
    - **G1 dirt** (``UAEPrsCp``): ``race_year`` + ``race`` + ``post_position`` when RES includes
      that race (Arabian cards are often omitted from TB ``.RES`` exports)
    """
    if isinstance(results, (str, Path)):
        res = load_results_directory(Path(results))
    else:
        res = results

    out = df.copy() if copy else df
    for col in ("date", "horse_name", "post_position", "track", "todays_race_classification", "race"):
        if col not in out.columns:
            raise KeyError(f"DataFrame must include {col!r}")

    if "official_finish_position" not in out.columns:
        out["official_finish_position"] = pd.NA
    if "official_final_odds" not in out.columns:
        out["official_final_odds"] = pd.NA

    if res.empty:
        print("Warning: no .RES results loaded; skipping official merge.", file=sys.stderr)
        return out

    prk_ref = _preakness_results_table(res)
    sb_ref = _sir_barton_results_table(res)
    g1_ref = _g1_dirt_results_table(res)
    card_ref = _card_date_results_table(res)

    # --- Preakness ---
    prk_mask = (out["track"].astype(str).str.strip() == "PIM") & out[
        "todays_race_classification"
    ].astype(str).str.contains(_PREAKNESS_CLASS, na=False)
    if prk_mask.any() and not prk_ref.empty:
        sub = out.loc[prk_mask].copy()
        sub = sub.drop(columns=["official_finish_position", "official_final_odds"], errors="ignore")
        sub["race_year"] = _race_year_series(sub["date"])
        sub["horse_name_key"] = sub["horse_name"].map(normalize_horse_name_key)
        joined = sub.merge(prk_ref, on=["race_year", "horse_name_key"], how="left")
        if len(joined) != len(sub):
            raise RuntimeError("Preakness merge row count mismatch")
        if warn_name_mismatches:
            missing = joined[joined["official_finish_position"].isna()]
            for _idx, row in missing.iterrows():
                print(
                    f"Warning: Preakness row without .RES finish year={row.get('race_year')} "
                    f"horse={row.get('horse_name')!r}",
                    file=sys.stderr,
                )
        out.loc[prk_mask, "official_finish_position"] = joined["official_finish_position"].values
        out.loc[prk_mask, "official_final_odds"] = joined["official_final_odds"].values

    # --- Sir Barton ---
    sb_mask = (out["track"].astype(str).str.strip() == "PIM") & out[
        "todays_race_classification"
    ].astype(str).str.contains(_SIR_BARTON_CLASS, na=False)
    if sb_mask.any() and not sb_ref.empty:
        sub = out.loc[sb_mask].copy()
        sub = sub.drop(columns=["official_finish_position", "official_final_odds"], errors="ignore")
        sub["race_year"] = _race_year_series(sub["date"])
        sub["horse_name_key"] = sub["horse_name"].map(normalize_horse_name_key)
        joined = sub.merge(sb_ref, on=["race_year", "horse_name_key"], how="left")
        if len(joined) != len(sub):
            raise RuntimeError("Sir Barton merge row count mismatch")
        if warn_unmatched_sir_barton:
            for _idx, row in joined[joined["official_finish_position"].isna()].iterrows():
                print(
                    f"Warning: Sir Barton row without official finish year={row.get('race_year')} "
                    f"horse={row.get('horse_name')!r}",
                    file=sys.stderr,
                )
        out.loc[sb_mask, "official_finish_position"] = joined["official_finish_position"].values
        out.loc[sb_mask, "official_final_odds"] = joined["official_final_odds"].values

    # --- G1 dirt (UAE President's Cup) ---
    g1_mask = (out["track"].astype(str).str.strip() == "PIM") & out[
        "todays_race_classification"
    ].astype(str).str.contains(_G1_DIRT_CLASS, na=False)
    if g1_mask.any():
        sub = out.loc[g1_mask].copy()
        sub = sub.drop(columns=["official_finish_position", "official_final_odds"], errors="ignore")
        sub["race_year"] = _race_year_series(sub["date"])
        sub["post_position_int"] = pd.to_numeric(sub["post_position"], errors="coerce")
        sub["race_int"] = pd.to_numeric(sub["race"], errors="coerce")
        sub["card_date_norm"] = pd.to_datetime(sub["date"], errors="coerce").dt.normalize()

        if not g1_ref.empty:
            joined = sub.merge(
                g1_ref.rename(columns={"post_position": "_ref_post_key", "race": "_ref_race_key"}),
                left_on=["race_year", "race_int", "post_position_int"],
                right_on=["race_year", "_ref_race_key", "_ref_post_key"],
                how="left",
            )
        else:
            joined = sub.merge(
                card_ref.rename(columns={"post_position": "_ref_post_key", "race": "_ref_race_key"}),
                left_on=["card_date_norm", "race_int", "post_position_int"],
                right_on=["card_date", "_ref_race_key", "_ref_post_key"],
                how="left",
            )

        if len(joined) != len(sub):
            raise RuntimeError("G1 dirt merge row count mismatch")

        missing = joined["official_finish_position"].isna().sum()
        if missing:
            print(
                f"Warning: {missing} G1 dirt (UAEPrsCp) row(s) have no .RES finish "
                "(Arabian races are often absent from TB results files).",
                file=sys.stderr,
            )

        out.loc[g1_mask, "official_finish_position"] = joined["official_finish_position"].values
        out.loc[g1_mask, "official_final_odds"] = joined["official_final_odds"].values

    return out


def merge_official_pim_results_for_drf(
    df: pd.DataFrame,
    drf_path: str | Path,
    results_dir: str | Path,
    **kwargs: object,
) -> pd.DataFrame:
    """Merge using the ``.RES`` file that pairs with a single ``.DRF`` (same basename)."""
    res_path = results_path_for_drf(drf_path, results_dir)
    if res_path is None:
        return merge_official_pim_results(df, load_results_directory(results_dir), **kwargs)
    return merge_official_pim_results(df, load_results_file(res_path), **kwargs)
