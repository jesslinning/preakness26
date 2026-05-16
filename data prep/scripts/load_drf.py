"""Load a Brisnet Single-File DRF (.DRF) into a pandas DataFrame with named columns.

Usage:
    from load_drf import load_drf
    df = load_drf("CDX0503.DRF")
    print(df.shape)                    # (n_entries, 1435)
    print(df[["race", "post_position", "horse_name"]].head())

Column names come from brisnet_columns.BRISNET_COLUMNS, which mirrors the
1,435-field spec at:
    https://support.brisnet.com/hc/en-us/articles/360056092092

Past-performance fields (last 10 starts) carry _pp1..._pp10 suffixes, so you
can pull a single horse's PP block with a regex select, e.g.:
    df.filter(regex=r"_pp\\d+$")

Per-race standardization and ranks: ``add_field_relative_features``,
``morning_line_implied_probability``.

Kentucky Derby rows: ``select_kentucky_derby`` (uses Brisnet ``KyDerby`` class code,
not a bare ``"DERBY"`` substring).

Preakness Stakes rows: ``select_preakness_stakes`` (Pimlico ``PIM`` or stakes-product
``PRK``, plus Brisnet ``Preaknes-G1`` classification — note the shortened ``Preaknes``
spelling). Use ``normalize_pimlico_track_codes`` so prediction rows match training.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from brisnet_columns import BRISNET_COLUMNS


# Handicapping features: raw numeric columns get within-field `{col}_field_z` and
# `{col}_field_rank` via `add_field_relative_features`. Morning line uses implied
# probability instead (see `morning_line_implied_probability`).
_FIELD_RELATIVE_BASE_COLS: list[str] = [
    "bris_prime_power_rating",
    "quirin_style_speed_points",
    "days_since_last_race",
    "weight",
    "apprentice_wgt_allow",
    "trainer_sts_current_meet",
    "trainer_wins_current_meet",
    "trainer_places_current_meet",
    "trainer_shows_current_meet",
    "jockey_sts_current_meet",
    "jockey_wins_current_meet",
    "jockey_places_current_meet",
    "jockey_shows_current_meet",
    "tj_combo_starts_365d",
    "tj_combo_wins_365d",
    "tj_combo_places_365d",
    "tj_combo_shows_365d",
    "tj_combo_roi_2_365d",
    "tj_combo_sts_meet",
    "tj_combo_wins_meet",
    "tj_combo_places_meet",
    "tj_combo_shows_meet",
    "tj_combo_roi_meet",
    "trainer_roi_current_year",
    "trainer_roi_previous_year",
    "jockey_roi_current_year",
    "jockey_roi_previous_year",
    "bris_dirt_pedigree_rating",
    "bris_mud_pedigree_rating",
    "bris_turf_pedigree_rating",
    "bris_dist_pedigree_rating",
    "best_bris_speed_fast_track",
    "best_bris_speed_turf",
    "best_bris_speed_off_track",
    "best_bris_speed_distance",
    "best_bris_speed_all_weather",
    "best_bris_speed_life",
    "best_bris_speed_most_recent_yr",
    "best_bris_speed_2nd_most_recent_yr",
    "best_bris_speed_todays_track",
    "key_trnr_stat_1_starts",
    "key_trnr_stat_1_win_pct",
    "key_trnr_stat_1_itm_pct",
    "key_trnr_stat_1_roi",
    "key_trnr_stat_2_starts",
    "key_trnr_stat_2_win_pct",
    "key_trnr_stat_2_itm_pct",
    "key_trnr_stat_2_roi",
    "key_trnr_stat_3_starts",
    "key_trnr_stat_3_win_pct",
    "key_trnr_stat_3_itm_pct",
    "key_trnr_stat_3_roi",
    "key_trnr_stat_4_starts",
    "key_trnr_stat_4_win_pct",
    "key_trnr_stat_4_itm_pct",
    "key_trnr_stat_4_roi",
    "key_trnr_stat_5_starts",
    "key_trnr_stat_5_win_pct",
    "key_trnr_stat_5_itm_pct",
    "key_trnr_stat_5_roi",
    "key_trnr_stat_6_starts",
    "key_trnr_stat_6_win_pct",
    "key_trnr_stat_6_itm_pct",
    "key_trnr_stat_6_roi",
    "jky_at_dis_starts",
    "jky_at_dis_wins",
    "jky_at_dis_places",
    "jky_at_dis_shows",
    "jky_at_dis_roi",
    "jky_at_dis_earnings",
    *[f"rank_of_work_{i}" for i in range(1, 13)],
]

FIELD_RELATIVE_NUMERIC_COLUMNS: tuple[str, ...] = tuple(_FIELD_RELATIVE_BASE_COLS)

# Grouping key for ``add_field_relative_features``: one tuple = one race’s entrants (the “field”).
# Z-scores and ranks are **within that race only**, never pooled across other races on the same card
# or date. Includes ``track`` so multi-track DRFs stay unambiguous; use ``race_keys=`` to override.
FIELD_RELATIVE_GROUP_KEYS: tuple[str, ...] = ("track", "date", "race")

# Rank 1 = smallest assigned weight (lighter burden); other columns default to rank 1 = largest value.
_RANK_LOWER_VALUE_IS_BETTER: frozenset[str] = frozenset({"weight"})

PIMLICO_TRACK_CODE = "PIM"
"""Brisnet track code on full Pimlico cards (e.g. ``PIM0517-2025.DRF``)."""

BRISNET_PREAKNESS_STAKES_PRODUCT_TRACK = "PRK"
"""Brisnet track code on the stakes-only Preakness product (e.g. ``PRK0516-2026.DRF``)."""

PIMLICO_TRACK_ALIASES = frozenset({PIMLICO_TRACK_CODE, BRISNET_PREAKNESS_STAKES_PRODUCT_TRACK})

__all__ = [
    "FIELD_RELATIVE_GROUP_KEYS",
    "FIELD_RELATIVE_NUMERIC_COLUMNS",
    "add_field_relative_features",
    "load_drf",
    "morning_line_implied_probability",
    "past_performances_long",
    "select_kentucky_derby",
    "normalize_pimlico_track_codes",
    "select_preakness_stakes",
    "select_sir_barton_stakes",
    "select_preakness_training_stakes",
    "PIMLICO_TRACK_CODE",
    "BRISNET_PREAKNESS_STAKES_PRODUCT_TRACK",
]


def _pimlico_track_mask(track: pd.Series, track_code: str = PIMLICO_TRACK_CODE) -> pd.Series:
    """Match Pimlico rows; default *track_code* accepts full-card ``PIM`` and stakes ``PRK``."""
    tc = track_code.strip()
    t = track.astype(str).str.strip()
    if tc == PIMLICO_TRACK_CODE:
        return t.isin(PIMLICO_TRACK_ALIASES)
    return t == tc


def normalize_pimlico_track_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Map stakes-product ``PRK`` to ``PIM`` so prediction rows align with training cards."""
    if "track" not in df.columns:
        return df
    out = df.copy()
    prk = out["track"].astype(str).str.strip() == BRISNET_PREAKNESS_STAKES_PRODUCT_TRACK
    if prk.any():
        out.loc[prk, "track"] = PIMLICO_TRACK_CODE
    return out


def load_drf(path: str | Path) -> pd.DataFrame:
    """Read a Brisnet Single DRF file into a DataFrame.

    Loaded as strings on purpose — the spec mixes character and numeric fields,
    and many "numeric" fields are sentinel-coded (e.g. -99 for missing). Cast
    the columns you care about explicitly with pd.to_numeric(..., errors="coerce").

    The ``date`` column is parsed to timezone-naive datetimes (Brisnet ``YYYYMMDD``).
    """
    df = pd.read_csv(
        path,
        header=None,
        names=BRISNET_COLUMNS,
        quotechar='"',
        skipinitialspace=True,    # Brisnet pads numerics with leading spaces
        dtype=str,
        na_values=[""],
        keep_default_na=True,
        encoding="latin-1",       # Brisnet files are not UTF-8
        engine="python",          # tolerant of the occasional ragged trailing comma
    )
    # Strip whitespace from every string cell — Brisnet right-pads CHAR fields.
    for c in df.columns:
        df[c] = df[c].str.strip() if df[c].dtype == object else df[c]

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")

    return df


def select_kentucky_derby(
    df: pd.DataFrame,
    *,
    track_code: str = "CD",
    require_unique_race: bool = True,
) -> pd.DataFrame:
    """Return rows for the Kentucky Derby stake from a loaded DRF frame.

    Filters to ``track`` matching *track_code* (default Churchill Downs ``CD``) and
    ``todays_race_classification`` containing ``KyDerby`` (e.g. ``KyDerby-G1``).

    Do **not** match on the substring ``"DERBY"`` alone — other races (e.g. Derby
    City Distaff) also contain that text.

    Parameters
    ----------
    require_unique_race
        If True, raises when there are zero matching rows or more than one distinct
        ``race`` number among matches.
    """
    need = ("track", "todays_race_classification", "race")
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise KeyError(f"DataFrame missing required columns: {missing}")

    cd = df["track"].str.strip() == track_code.strip()
    ky = df["todays_race_classification"].str.contains("KyDerby", na=False)
    out = df.loc[cd & ky].copy()

    if not require_unique_race:
        return out

    n = out["race"].nunique()
    if n == 0:
        raise ValueError(
            f"No Kentucky Derby (KyDerby classification) rows for track {track_code!r}."
        )
    if n > 1:
        raise ValueError(
            "Expected a single KyDerby race number in this file; found "
            f"{n}: {sorted(out['race'].dropna().unique().tolist())!r}"
        )
    return out


def select_preakness_stakes(
    df: pd.DataFrame,
    *,
    track_code: str = "PIM",
    require_unique_race: bool = True,
) -> pd.DataFrame:
    """Return rows for the Preakness Stakes from a loaded DRF frame.

    Filters to ``track`` matching *track_code* (default Pimlico ``PIM``) and
    ``todays_race_classification`` containing ``Preaknes`` (Brisnet uses
    ``Preaknes-G1``, not the full word ``Preakness``).

    Race number varies by year (e.g. 2020); do not rely on a fixed ``race`` alone.
    """
    need = ("track", "todays_race_classification", "race")
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise KeyError(f"DataFrame missing required columns: {missing}")

    pim = _pimlico_track_mask(df["track"], track_code)
    prk = df["todays_race_classification"].str.contains("Preaknes", na=False)
    out = df.loc[pim & prk].copy()

    if not require_unique_race:
        return out

    n = out["race"].nunique()
    if n == 0:
        raise ValueError(
            f"No Preakness Stakes (Preaknes classification) rows for track {track_code!r}."
        )
    if n > 1:
        raise ValueError(
            "Expected a single Preaknes race number in this file; found "
            f"{n}: {sorted(out['race'].dropna().unique().tolist())!r}"
        )
    return out


def select_sir_barton_stakes(
    df: pd.DataFrame,
    *,
    track_code: str = "PIM",
    require_unique_race: bool = True,
) -> pd.DataFrame:
    """Return rows for the Sir Barton Stakes from a loaded DRF frame.

    Filters to ``track`` matching *track_code* (default Pimlico ``PIM``) and
    ``todays_race_classification`` containing ``SirBarton`` (e.g. ``SirBartonB100k``).
    """
    need = ("track", "todays_race_classification", "race")
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise KeyError(f"DataFrame missing required columns: {missing}")

    pim = _pimlico_track_mask(df["track"], track_code)
    sb = df["todays_race_classification"].str.contains("SirBarton", na=False)
    out = df.loc[pim & sb].copy()

    if not require_unique_race:
        return out

    n = out["race"].nunique()
    if n == 0:
        raise ValueError(
            f"No Sir Barton Stakes (SirBarton classification) rows for track {track_code!r}."
        )
    if n > 1:
        raise ValueError(
            "Expected a single SirBarton race number in this file; found "
            f"{n}: {sorted(out['race'].dropna().unique().tolist())!r}"
        )
    return out


def select_g1_dirt_stakes(
    df: pd.DataFrame,
    *,
    track_code: str = "PIM",
    require_unique_race: bool = True,
) -> pd.DataFrame:
    """Return rows for the UAE President's Cup G1 dirt race (``UAEPrsCp-G1``) when on the card."""
    need = ("track", "todays_race_classification", "race")
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise KeyError(f"DataFrame missing required columns: {missing}")

    pim = _pimlico_track_mask(df["track"], track_code)
    g1 = df["todays_race_classification"].str.contains("UAEPrsCp", na=False)
    out = df.loc[pim & g1].copy()

    if not require_unique_race:
        return out

    n = out["race"].nunique()
    if n == 0:
        raise ValueError(
            f"No UAE President's Cup (UAEPrsCp classification) rows for track {track_code!r}."
        )
    if n > 1:
        raise ValueError(
            "Expected a single UAEPrsCp race number in this file; found "
            f"{n}: {sorted(out['race'].dropna().unique().tolist())!r}"
        )
    return out


def select_preakness_training_stakes(
    df: pd.DataFrame,
    *,
    track_code: str = "PIM",
    include_g1_dirt: bool = False,
) -> pd.DataFrame:
    """Preakness and Sir Barton rows; optional G1 dirt (UAEPrsCp) when labeled in ``.RES``."""
    prk = select_preakness_stakes(df, track_code=track_code, require_unique_race=False)
    sbt = select_sir_barton_stakes(df, track_code=track_code, require_unique_race=False)
    parts = [prk, sbt]
    if include_g1_dirt:
        g1 = select_g1_dirt_stakes(df, track_code=track_code, require_unique_race=False)
        parts.append(g1)
    out = pd.concat(parts, ignore_index=True)
    if out.empty:
        raise ValueError(f"No Preakness-week training stake rows for track {track_code!r}.")
    return out


_AMERICAN_ODDS_RE = re.compile(r"^\s*([+-])\s*(\d+(?:\.\d+)?)\s*$")
_FRACTIONAL_ODDS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)\s*$")


def morning_line_implied_probability(s: pd.Series) -> pd.Series:
    """Naive implied win probability from morning-line odds (no de-vig).

    Supports common Brisnet decimal strings (e.g. ``\"15.00\"``, ``\"3.50\"``),
    US fractional profit/stake (e.g. ``\"5-2\"``, ``\"7/2\"`` → decimal = a/b + 1),
    American odds (``\"+400\"``, ``\"-150\"``), and ``\"EVEN\"``.
    Invalid or missing values become NaN.
    """

    def _one(raw: object) -> float:
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            return np.nan
        st = str(raw).strip()
        if not st:
            return np.nan
        upper = st.upper()
        if upper == "EVEN":
            return 1.0 / 2.0  # 1-1 → decimal 2.0
        m_am = _AMERICAN_ODDS_RE.match(st)
        if m_am:
            sign, mag_s = m_am.group(1), m_am.group(2)
            mag = float(mag_s)
            if sign == "+":
                dec = mag / 100.0 + 1.0
            else:
                if mag == 0:
                    return np.nan
                dec = 100.0 / mag + 1.0
            return 1.0 / dec if dec > 1.0 else np.nan
        m_fr = _FRACTIONAL_ODDS_RE.match(st)
        if m_fr:
            a, b = float(m_fr.group(1)), float(m_fr.group(2))
            if b == 0:
                return np.nan
            dec = a / b + 1.0
            return 1.0 / dec if dec > 1.0 else np.nan
        x = pd.to_numeric(st, errors="coerce")
        if pd.isna(x):
            return np.nan
        # Decimal (European-style) total-return odds — Brisnet sample uses these.
        return (1.0 / x) if x > 1.0 else np.nan

    return s.map(_one).astype(float)


def add_field_relative_features(
    df: pd.DataFrame,
    *,
    race_keys: tuple[str, ...] | list[str] | None = None,
    numeric_columns: tuple[str, ...] | list[str] | None = None,
    rank_lower_value_is_better: frozenset[str] | set[str] | None = None,
    copy: bool = True,
) -> pd.DataFrame:
    """Add per-race z-scores and ranks for handicapping numerics (Excel-style STDDEV).

    Rows are grouped by a **race identity** (default :data:`FIELD_RELATIVE_GROUP_KEYS`:
    ``track``, ``date``, ``race``). Mean, standard deviation, and ranks use **only**
    horses in that same race — never all races on the program, never “whole day”
    pooling. Filtering the frame down to one race (e.g. Kentucky Derby) before
    calling this function yields the same z-scores/ranks for those horses as when
    they appear in a full-card ``DataFrame``, because the group is unchanged.

    For each selected column, adds ``{col}_field_z`` and ``{col}_field_rank`` within
    each group. Z-score uses sample standard deviation (``ddof=1``, like
    ``STDEV`` / ``STDEV.S``). When within-group ``std`` is 0, z-scores are NaN.

    Morning line is handled separately: ``morn_line_implied_prob``,
    ``morn_line_implied_prob_field_rank``, ``morn_line_implied_prob_field_z``
    (rank 1 = highest implied probability / shortest-price notion of “favorite”).

    Columns not present in ``df`` are skipped. If ``morn_line_odds`` is missing,
    implied-probability columns are omitted.

    Parameters
    ----------
    race_keys
        Columns identifying one race (default: each of :data:`FIELD_RELATIVE_GROUP_KEYS`
        that exists in ``df``). Use e.g. ``("date", "race")`` only if you are sure
        ``race`` numbers are unique within ``date`` for your file.
    numeric_columns
        Base columns to expand (default: :data:`FIELD_RELATIVE_NUMERIC_COLUMNS`).
    rank_lower_value_is_better
        Columns where rank 1 should be the **minimum** numeric value (default: lighter
        ``weight`` only).
    copy
        If True, operate on a copy of ``df``.
    """
    out = df.copy() if copy else df
    keys = list(race_keys) if race_keys is not None else []
    if not keys:
        keys = [k for k in FIELD_RELATIVE_GROUP_KEYS if k in out.columns]
    if not keys:
        out["_field_group"] = 0
        keys = ["_field_group"]

    base_cols = list(numeric_columns) if numeric_columns is not None else list(FIELD_RELATIVE_NUMERIC_COLUMNS)
    lower_better = (
        _RANK_LOWER_VALUE_IS_BETTER
        if rank_lower_value_is_better is None
        else frozenset(rank_lower_value_is_better)
    )

    g = out.groupby(keys, dropna=False)

    new_cols: dict[str, pd.Series] = {}
    for col in base_cols:
        if col not in out.columns:
            continue
        num = pd.to_numeric(out[col], errors="coerce")
        mean = g[col].transform(lambda x: pd.to_numeric(x, errors="coerce").mean())
        std = g[col].transform(lambda x: pd.to_numeric(x, errors="coerce").std(ddof=1))
        z = (num - mean) / std.replace(0, np.nan)
        ascending = col in lower_better
        rk = g[col].transform(
            lambda x: pd.to_numeric(x, errors="coerce").rank(ascending=ascending, method="min")
        )
        new_cols[f"{col}_field_z"] = z
        new_cols[f"{col}_field_rank"] = rk

    if "morn_line_odds" in out.columns:
        imp = morning_line_implied_probability(out["morn_line_odds"])
        new_cols["morn_line_implied_prob"] = imp
        g_imp = out.assign(_imp=imp).groupby(keys, dropna=False)["_imp"]
        mean_i = g_imp.transform("mean")
        std_i = g_imp.transform(lambda x: x.std(ddof=1))
        new_cols["morn_line_implied_prob_field_z"] = (imp - mean_i) / std_i.replace(0, np.nan)
        new_cols["morn_line_implied_prob_field_rank"] = g_imp.transform(
            lambda x: x.rank(ascending=False, method="min")
        )

    if "_field_group" in out.columns and "_field_group" not in (race_keys or ()):
        out = out.drop(columns=["_field_group"])

    if new_cols:
        out = pd.concat([out, pd.DataFrame(new_cols, index=out.index)], axis=1)

    return out


def past_performances_long(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the 10-deep _ppN columns into a long-format frame.

    One row per (entry, race_back_index). Useful for time-series style analysis
    of a horse's recent form.
    """
    pp_cols = [c for c in df.columns if c.endswith(tuple(f"_pp{i}" for i in range(1, 11)))]
    id_cols = ["track", "date", "race", "post_position", "horse_name"]
    id_cols = [c for c in id_cols if c in df.columns]

    long = df.melt(id_vars=id_cols, value_vars=pp_cols,
                   var_name="field_pp", value_name="value")
    # Split "field_name_ppN" -> field_name, race_back
    parts = long["field_pp"].str.rsplit("_pp", n=1, expand=True)
    long["field"] = parts[0]
    long["race_back"] = parts[1].astype(int)
    long = long.drop(columns=["field_pp"])

    # Pivot so each PP field becomes its own column, indexed by entry + race_back.
    wide = long.pivot_table(index=id_cols + ["race_back"],
                            columns="field",
                            values="value",
                            aggfunc="first")
    wide.columns.name = None
    # PP field names can duplicate id_cols (e.g. post_position_ppN -> "post_position").
    dup = set(wide.columns) & set(id_cols)
    if dup:
        wide = wide.rename(columns={c: f"pp_{c}" for c in dup})
    wide = wide.reset_index()
    return wide.sort_values(id_cols + ["race_back"]).reset_index(drop=True)


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "CDX0503.DRF"
    df = load_drf(src)
    print(f"Loaded {src}: {df.shape[0]} entries, {df.shape[1]} columns")
    print(df[["track", "date", "race", "post_position", "horse_name"]].head(12).to_string(index=False))
