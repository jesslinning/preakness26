"""Combine all Brisnet .DRF files under data/raw into processed outputs.

Writes (training / history):
  data/processed/combined.csv             — stake entries (Derby, or Preakness-week stakes; see ``--stakes``)
  data/processed/combined_pp_long.csv    — past_performances_long on that frame

When ``--stakes derby``, the latest prediction card (default ``CDX0502-2026.DRF``) is **excluded**
from the training combine and processed separately **without** official results merge:

  data/processed/predictions.csv         — Derby field for scoring / inference
  data/processed/predictions_pp_long.csv — PP-long for that card

For ``--stakes preakness``, prediction export is off by default (no default holdout DRF).

By default, rows are restricted to the target stake on each card. Use ``--full-card`` to keep
every race in every raw DRF.

Official results from Brisnet ``data/raw/results/*.RES`` are merged onto training rows only;
prediction exports omit targets.

Wide training rows include ``add_field_relative_features`` columns (``*_field_z``, ``*_field_rank``,
morning-line implied probability and ranks) after labels are finalized, then extra stake targets
(``target_ml_rank_minus_finish``, ``target_top5_ml_rank_gt4``, ``target_deep_closer_top5``)
when morning-line columns exist.

Run from ``data prep``:  python scripts/process_raw_drfs.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

import pandas as pd

from derby_reference import (
    attach_derby_labels_to_pp_long,
    finalize_derby_training_columns,
    merge_official_derby_results,
)
from load_drf import (
    add_field_relative_features,
    load_drf,
    normalize_pimlico_track_codes,
    past_performances_long,
    select_kentucky_derby,
    select_preakness_stakes,
    select_preakness_training_stakes,
)
from pim_results import merge_official_pim_results
from stakes_targets import add_stakes_extras_targets

Stakes = Literal["derby", "preakness"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


DEFAULT_PREDICTION_DRF_DERBY = "CDX0502-2026.DRF"


def _resolve_prediction_drf(raw_dir: Path, prediction_drf: str) -> Path | None:
    """Locate a prediction DRF under *raw_dir* (basename or relative path, e.g. ``2026/PRK….DRF``)."""
    p = Path(prediction_drf)
    if p.is_file():
        return p.resolve()
    candidate = raw_dir / prediction_drf
    if candidate.is_file():
        return candidate.resolve()
    name = p.name
    matches = sorted(raw_dir.rglob(name))
    if not matches:
        return None
    if len(matches) > 1:
        raise FileNotFoundError(
            f"Multiple .DRF files named {name!r} under {raw_dir}: "
            + ", ".join(str(m.relative_to(raw_dir)) for m in matches)
        )
    return matches[0].resolve()


def _prediction_drf_basename(prediction_drf: str) -> str:
    return Path(prediction_drf).name


def _list_drf_files(raw_dir: Path, *, exclude_names: frozenset[str] | None = None) -> list[Path]:
    if not raw_dir.is_dir():
        return []
    paths = [p for p in raw_dir.iterdir() if p.is_file() and p.suffix.upper() == ".DRF"]
    if exclude_names:
        paths = [p for p in paths if p.name not in exclude_names]
    return sorted(paths, key=lambda p: p.name.lower())


def _save_table(df: pd.DataFrame, dest_base: Path) -> Path:
    """Write UTF-8 CSV (no index column)."""
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    out_path = dest_base.with_suffix(".csv")
    df.to_csv(out_path, index=False, encoding="utf-8")
    return out_path


def _default_results_dir(root: Path) -> Path:
    return root / "data" / "raw" / "results"


def _default_reference_csv(root: Path, stakes: Stakes) -> Path:
    return root / "data" / "reference" / "kentucky_derby_results_2017_2025.csv"


def combine_raw_drfs(
    raw_dir: Path,
    processed_dir: Path,
    *,
    stakes: Stakes = "preakness",
    source_column: str = "_source_drf",
    reference_csv: Path | None = None,
    results_dir: Path | None = None,
    stake_only: bool = True,
    exclude_drf_names: frozenset[str] | None = None,
) -> tuple[Path, Path]:
    paths = _list_drf_files(raw_dir, exclude_names=exclude_drf_names)
    if not paths:
        raise FileNotFoundError(
            f"No .DRF files found in {raw_dir}"
            + (f" after excluding {sorted(exclude_drf_names)!r}" if exclude_drf_names else "")
        )

    chunks: list[pd.DataFrame] = []
    for p in paths:
        chunks.append(load_drf(p).assign(**{source_column: p.name}))

    combined = pd.concat(chunks, ignore_index=True)

    if stake_only:
        if stakes == "derby":
            combined = select_kentucky_derby(combined, require_unique_race=False)
        else:
            combined = select_preakness_training_stakes(combined)

    root = _repo_root()
    if stakes == "derby":
        ref_path = (reference_csv if reference_csv is not None else _default_reference_csv(root, stakes)).resolve()
        if ref_path.is_file():
            combined = merge_official_derby_results(combined, ref_path)
        else:
            print(
                f"Warning: reference results not found at {ref_path}; "
                "skipping merge and training targets (year, target_FP, target_top3, target_top5).",
                file=sys.stderr,
            )
    else:
        res_dir = (results_dir if results_dir is not None else _default_results_dir(root)).resolve()
        if not res_dir.is_dir():
            print(
                f"Warning: results directory not found at {res_dir}; "
                "skipping official merge and training targets.",
                file=sys.stderr,
            )
        else:
            combined = merge_official_pim_results(combined, res_dir, warn_unmatched_sir_barton=False)

    if "official_finish_position" in combined.columns:
        combined = finalize_derby_training_columns(combined)
        combined = add_field_relative_features(combined)
        combined = add_stakes_extras_targets(combined)

    _print_training_summary(combined)

    wide_path = _save_table(combined, processed_dir / "combined")

    pp_long = past_performances_long(combined)
    if "target_FP" in combined.columns:
        pp_long = attach_derby_labels_to_pp_long(pp_long, combined)
    long_path = _save_table(pp_long, processed_dir / "combined_pp_long")

    return wide_path, long_path


def export_predictions_drf(
    raw_dir: Path,
    processed_dir: Path,
    prediction_drf_name: str,
    *,
    stakes: Stakes = "preakness",
    source_column: str = "_source_drf",
    stake_only: bool = True,
) -> tuple[Path | None, Path | None]:
    """Holdout DRF extract: no results merge, adds ``year`` from ``date``."""
    pred_path = _resolve_prediction_drf(raw_dir, prediction_drf_name)
    if pred_path is None:
        return None, None

    df = normalize_pimlico_track_codes(load_drf(pred_path)).assign(**{source_column: pred_path.name})
    if stake_only:
        if stakes == "derby":
            df = select_kentucky_derby(df, require_unique_race=False)
        else:
            df = select_preakness_stakes(df, require_unique_race=False)
    df["year"] = pd.to_datetime(df["date"], errors="coerce").dt.year

    df = add_field_relative_features(df)
    wide_path = _save_table(df, processed_dir / "predictions")
    pp_long = past_performances_long(df)
    long_path = _save_table(pp_long, processed_dir / "predictions_pp_long")
    return wide_path, long_path


def _print_training_summary(df: pd.DataFrame) -> None:
    if "year" not in df.columns or len(df) == 0:
        return
    print("Training rows by year:")
    print(df.groupby("year").size().sort_index().to_string())
    if "todays_race_classification" in df.columns:
        cls = df["todays_race_classification"].astype(str)
        is_prk = cls.str.contains("Preaknes", na=False)
        is_sb = cls.str.contains("SirBarton", na=False)
        is_g1 = cls.str.contains("UAEPrsCp", na=False)
        print(f"  Preakness rows: {int(is_prk.sum())}")
        print(f"  Sir Barton rows: {int(is_sb.sum())}")
        print(f"  G1 dirt (UAEPrsCp) rows: {int(is_g1.sum())}")
    print(f"Total training rows: {len(df)}")


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stakes",
        choices=("derby", "preakness"),
        default="preakness",
        help="Which stake(s) to filter and merge (default: preakness = Preakness + Sir Barton)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=root / "data" / "raw",
        help="Directory containing .DRF files (default: data/raw)",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=root / "data" / "processed",
        help="Output directory (default: data/processed)",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=None,
        help="Derby only: official results CSV (default: data/reference/kentucky_derby_results_2017_2025.csv)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Preakness: directory of Brisnet .RES files (default: data/raw/results)",
    )
    parser.add_argument(
        "--full-card",
        action="store_true",
        help="Include all races from each DRF (default: stake runners only)",
    )
    parser.add_argument(
        "--prediction-drf",
        type=str,
        default=None,
        help=(
            "Prediction DRF under raw/ (basename or subpath, e.g. 2026/PRK0516-2026.DRF). "
            "Excluded from training combine. "
            f"Default: {DEFAULT_PREDICTION_DRF_DERBY!r} when --stakes derby; empty (disabled) for preakness."
        ),
    )
    parser.add_argument(
        "--skip-predictions-export",
        action="store_true",
        help="Do not write predictions.csv / predictions_pp_long.csv",
    )
    parser.add_argument(
        "--predictions-only",
        action="store_true",
        help="Only export --prediction-drf (skip training combine)",
    )
    args = parser.parse_args(argv)

    stakes: Stakes = args.stakes
    if args.prediction_drf is None:
        prediction_name = DEFAULT_PREDICTION_DRF_DERBY.strip() if stakes == "derby" else ""
    else:
        prediction_name = args.prediction_drf.strip()

    raw_dir = args.raw_dir.resolve()
    processed_dir = args.processed_dir.resolve()

    exclude_names: frozenset[str] | None = None
    if prediction_name:
        exclude_names = frozenset({_prediction_drf_basename(prediction_name)})

    if not args.predictions_only:
        try:
            wide_path, long_path = combine_raw_drfs(
                raw_dir,
                processed_dir,
                stakes=stakes,
                reference_csv=args.reference_csv,
                results_dir=args.results_dir,
                stake_only=not args.full_card,
                exclude_drf_names=exclude_names,
            )
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 1

        n_train = len(_list_drf_files(raw_dir, exclude_names=exclude_names))
        print(f"Training combine: {n_train} DRF file(s) from {raw_dir}")
        if exclude_names:
            print(f"Excluded from training combine: {sorted(exclude_names)}")
        print(f"Wide combined -> {wide_path}")
        print(f"Long PP combined -> {long_path}")
    elif not prediction_name:
        print("--predictions-only requires --prediction-drf", file=sys.stderr)
        return 1

    if prediction_name and not args.skip_predictions_export:
        pw, pl = export_predictions_drf(
            raw_dir,
            processed_dir,
            prediction_name,
            stakes=stakes,
            stake_only=not args.full_card,
        )
        if pw is None:
            print(
                f"Note: prediction DRF {prediction_name!r} not found under {raw_dir}; "
                "skipped predictions export.",
                file=sys.stderr,
            )
        else:
            print(f"Predictions wide -> {pw}")
            print(f"Predictions PP long -> {pl}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
