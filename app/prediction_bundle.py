"""
Load DataRobot batch blend CSVs (one per strategy), merge on horse_name, and build
ensemble / longshot indices plus composite_score for the Preakness explorer.

Core blends (FP, top3, top5) feed ``composite_score``. Three longshot blends are
rank-normalized into ``longshot_index``. Companion ``predictions_{target}.meta.json``
files supply blend + child-model metadata for the Models tab.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CORE_TARGETS = ("target_FP", "target_top3", "target_top5")
LONGSHOT_TARGETS = (
    "target_ml_rank_minus_finish",
    "target_top5_ml_rank_gt4",
    "target_deep_closer_top5",
)
ALL_TARGETS = CORE_TARGETS + LONGSHOT_TARGETS

# Legacy Derby glob parser still recognizes these three only.
KNOWN_TARGETS = CORE_TARGETS

DEFAULT_BLEND_WEIGHTS = {
    "ensemble_top3": 0.5,
    "ensemble_top5": 0.4,
    "fp_strength": 0.1,
}

DEFAULT_LONGSHOT_BLEND_WEIGHTS = {
    "ml_beat_strength": 0.5,
    "longshot_top5_strict": 0.3,
    "longshot_top5_broad": 0.2,
}


@dataclass
class FileMeta:
    target: str
    model_label: str
    model_id: str
    path: str
    column_name: str


@dataclass
class CombinedPredictionBundle:
    """Wide frame (one row per horse) plus strategy metadata and blend weights."""

    wide: pd.DataFrame
    meta: list[FileMeta] = field(default_factory=list)
    strategies: list[dict[str, Any]] = field(default_factory=list)
    blend_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_BLEND_WEIGHTS)
    )
    longshot_blend_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_LONGSHOT_BLEND_WEIGHTS)
    )

    def to_json_payload(self) -> dict[str, Any]:
        """Records safe for JSON (NaN -> null). Frontend-friendly."""
        df = self.wide.replace({np.nan: None})
        return {
            "blend_weights": self.blend_weights,
            "longshot_blend_weights": self.longshot_blend_weights,
            "strategies": self.strategies,
            "meta": [asdict(m) for m in self.meta],
            "horses": df.to_dict(orient="records"),
            "columns": list(df.columns),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_predictions_dir() -> Path:
    return _repo_root() / "data prep" / "data" / "predictions"


def default_output_dir() -> Path:
    return _repo_root() / "app" / "output"


def parse_simple_prediction_filename(path: Path) -> str | None:
    """Parse ``predictions_{target}.csv`` (one blend per file)."""
    name = path.name
    if not name.startswith("predictions_") or not name.endswith(".csv"):
        return None
    stem = name[: -len(".csv")]
    target = stem[len("predictions_") :]
    if target in ALL_TARGETS:
        return target
    return None


def parse_prediction_filename(path: Path) -> tuple[str, str, str] | None:
    """
    Parse legacy ``predictions_{target}_{model_label}_{model_id}.csv``.

    ``model_id`` is the final underscore-separated segment (DataRobot model id).
    """
    name = path.name
    if not name.startswith("predictions_") or not name.endswith(".csv"):
        return None
    if parse_simple_prediction_filename(path) is not None:
        return None
    stem = name[: -len(".csv")]
    body = stem[len("predictions_") :]
    for tgt in KNOWN_TARGETS:
        prefix = tgt + "_"
        if body.startswith(prefix):
            remainder = body[len(prefix) :]
            idx = remainder.rfind("_")
            if idx <= 0:
                return None
            model_id = remainder[idx + 1 :]
            model_label = remainder[:idx]
            if not model_id or not model_label:
                return None
            return tgt, model_label, model_id
    return None


_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9]+")


def _column_slug(model_label: str, max_len: int = 48) -> str:
    s = _SLUG_SAFE.sub("_", model_label.strip()).strip("_")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "model"


def _value_column_for_target(target: str) -> str:
    if target in ("target_FP", "target_ml_rank_minus_finish"):
        return f"{target}_PREDICTION"
    if target in (
        "target_top3",
        "target_top5",
        "target_top5_ml_rank_gt4",
        "target_deep_closer_top5",
    ):
        return f"{target}_1_PREDICTION"
    raise ValueError(f"unknown target {target!r}")


def _prefix_for_target(target: str) -> str:
    return {
        "target_FP": "fp",
        "target_top3": "top3",
        "target_top5": "top5",
        "target_ml_rank_minus_finish": "ml_beat",
        "target_top5_ml_rank_gt4": "top5_gt4",
        "target_deep_closer_top5": "deep_closer",
    }[target]


def _rank_strength(series: pd.Series, *, ascending: bool) -> pd.Series:
    """Map values to [0, 1] field percentiles (higher = stronger)."""
    ranks = series.rank(method="average", ascending=ascending)
    n = len(series)
    return (ranks - 1) / max(n - 1, 1)


def _load_strategy_meta(meta_path: Path) -> dict[str, Any]:
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _read_blend_csv(path: Path, target: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as e:
        raise ValueError(f"{path}: empty CSV") from e
    if len(df) == 0:
        raise ValueError(f"{path}: no data rows")
    if "horse_name" not in df.columns:
        raise ValueError(f"{path}: missing horse_name")
    dup = df["horse_name"].duplicated()
    if dup.any():
        raise ValueError(
            f"{path}: duplicate horse_name rows: {df.loc[dup, 'horse_name'].tolist()}"
        )
    vc = _value_column_for_target(target)
    if vc not in df.columns:
        raise ValueError(f"{path}: missing column {vc!r}")
    return df


def _simple_blend_files_present(root: Path) -> bool:
    return any((root / f"predictions_{t}.csv").is_file() for t in ALL_TARGETS)


def _build_simple_bundle(
    root: Path,
    *,
    blend_weights: dict[str, float] | None,
    longshot_blend_weights: dict[str, float] | None,
) -> CombinedPredictionBundle:
    missing = [t for t in ALL_TARGETS if not (root / f"predictions_{t}.csv").is_file()]
    if missing:
        raise FileNotFoundError(
            f"Expected six blend CSVs under {root}; missing: {missing}"
        )

    strategies: list[dict[str, Any]] = []
    passthrough_cols = ("program_number", "morn_line_implied_prob_field_rank")
    wide: pd.DataFrame | None = None

    for target in ALL_TARGETS:
        csv_path = root / f"predictions_{target}.csv"
        meta_path = root / f"predictions_{target}.meta.json"
        df = _read_blend_csv(csv_path, target)
        vc = _value_column_for_target(target)

        if meta_path.is_file():
            meta = _load_strategy_meta(meta_path)
            meta.setdefault("target", target)
            meta.setdefault("prediction_path", str(csv_path.resolve()))
            strategies.append(meta)
        else:
            logger.warning("No meta JSON for %s at %s", target, meta_path)
            strategies.append(
                {
                    "target": target,
                    "prediction_path": str(csv_path.resolve()),
                    "child_models": [],
                }
            )

        keep = ["horse_name", *passthrough_cols, vc]
        keep = [c for c in keep if c in df.columns]
        part = df[keep].copy()

        if wide is None:
            wide = part
        else:
            merge_cols = ["horse_name", vc]
            wide = wide.merge(part[merge_cols], on="horse_name", how="inner")

    assert wide is not None
    n_expected = len(_read_blend_csv(root / f"predictions_{CORE_TARGETS[0]}.csv", CORE_TARGETS[0]))
    if len(wide) != n_expected:
        raise ValueError(
            f"horse_name alignment failed: merged {len(wide)} rows, expected {n_expected}"
        )

    wide["ensemble_fp_mean"] = wide[_value_column_for_target("target_FP")]
    wide["fp_strength"] = _rank_strength(wide["ensemble_fp_mean"], ascending=True)
    wide["ensemble_top3"] = wide[_value_column_for_target("target_top3")]
    wide["ensemble_top5"] = wide[_value_column_for_target("target_top5")]

    wide["ml_beat_strength"] = _rank_strength(
        wide[_value_column_for_target("target_ml_rank_minus_finish")],
        ascending=False,
    )
    wide["longshot_top5_strict"] = _rank_strength(
        wide[_value_column_for_target("target_top5_ml_rank_gt4")],
        ascending=False,
    )
    wide["longshot_top5_broad"] = _rank_strength(
        wide[_value_column_for_target("target_deep_closer_top5")],
        ascending=False,
    )

    lw = dict(DEFAULT_LONGSHOT_BLEND_WEIGHTS)
    if longshot_blend_weights:
        lw.update(longshot_blend_weights)
    wide["longshot_index"] = (
        lw["ml_beat_strength"] * wide["ml_beat_strength"]
        + lw["longshot_top5_strict"] * wide["longshot_top5_strict"]
        + lw["longshot_top5_broad"] * wide["longshot_top5_broad"]
    )

    w = dict(DEFAULT_BLEND_WEIGHTS)
    if blend_weights:
        w.update(blend_weights)
    wide["composite_score"] = (
        w.get("ensemble_top3", 0.5) * wide["ensemble_top3"].fillna(0)
        + w.get("ensemble_top5", 0.4) * wide["ensemble_top5"].fillna(0)
        + w.get("fp_strength", 0.1) * wide["fp_strength"].fillna(0)
    )

    _spearman_warning(wide)

    return CombinedPredictionBundle(
        wide=wide.sort_values("composite_score", ascending=False).reset_index(drop=True),
        meta=[],
        strategies=strategies,
        blend_weights=w,
        longshot_blend_weights=lw,
    )


def load_prediction_csv(path: Path, meta: FileMeta) -> pd.DataFrame:
    df = _read_blend_csv(path, meta.target)
    vc = _value_column_for_target(meta.target)
    out = df[["horse_name", vc]].rename(columns={vc: meta.column_name})
    return out


def _spearman_warning(wide: pd.DataFrame) -> None:
    if "ensemble_top3" not in wide.columns or "ensemble_fp_mean" not in wide.columns:
        return
    try:
        rho = wide["ensemble_top3"].corr(wide["ensemble_fp_mean"], method="spearman")
    except Exception:
        return
    if rho is None or np.isnan(rho):
        return
    if rho > 0.2:
        logger.warning(
            "Spearman(ensemble_top3, ensemble_fp_mean) = %.3f — expected strongly negative.",
            rho,
        )


def _build_legacy_bundle(
    root: Path,
    *,
    blend_weights: dict[str, float] | None,
) -> CombinedPredictionBundle:
    paths = sorted(root.glob("predictions_*.csv"))
    if not paths:
        raise FileNotFoundError(f"no predictions_*.csv under {root}")

    meta_list: list[FileMeta] = []
    frames: list[pd.DataFrame] = []

    for p in paths:
        parsed = parse_prediction_filename(p)
        if not parsed:
            logger.debug("skip non-matching file: %s", p.name)
            continue
        target, model_label, model_id = parsed
        slug = _column_slug(model_label)
        col = f"{_prefix_for_target(target)}__{slug}__{model_id}"
        m = FileMeta(
            target=target,
            model_label=model_label,
            model_id=model_id,
            path=str(p.resolve()),
            column_name=col,
        )
        try:
            frames.append(load_prediction_csv(p, m))
        except ValueError as e:
            logger.warning("skip %s: %s", p.name, e)
            continue
        meta_list.append(m)

    if not frames:
        raise ValueError(f"no valid legacy prediction files under {root}")

    wide = frames[0]
    for nxt in frames[1:]:
        wide = wide.merge(nxt, on="horse_name", how="inner")

    n0 = len(frames[0])
    if len(wide) != n0:
        raise ValueError(
            f"horse_name sets differ across files: merged {len(wide)} rows, expected {n0}"
        )

    fp_cols = [m.column_name for m in meta_list if m.target == "target_FP"]
    t3_cols = [m.column_name for m in meta_list if m.target == "target_top3"]
    t5_cols = [m.column_name for m in meta_list if m.target == "target_top5"]

    if fp_cols:
        wide["ensemble_fp_mean"] = wide[fp_cols].mean(axis=1)
        wide["fp_strength"] = _rank_strength(wide["ensemble_fp_mean"], ascending=True)
    else:
        wide["ensemble_fp_mean"] = np.nan
        wide["fp_strength"] = 0.5

    wide["ensemble_top3"] = wide[t3_cols].mean(axis=1) if t3_cols else np.nan
    wide["ensemble_top5"] = wide[t5_cols].mean(axis=1) if t5_cols else np.nan
    wide["longshot_index"] = np.nan
    wide["ml_beat_strength"] = np.nan
    wide["longshot_top5_strict"] = np.nan
    wide["longshot_top5_broad"] = np.nan

    w = dict(DEFAULT_BLEND_WEIGHTS)
    if blend_weights:
        w.update(blend_weights)

    wide["composite_score"] = (
        w.get("ensemble_top3", 0.5) * wide["ensemble_top3"].fillna(0)
        + w.get("ensemble_top5", 0.4) * wide["ensemble_top5"].fillna(0)
        + w.get("fp_strength", 0.1) * wide["fp_strength"].fillna(0)
    )

    _spearman_warning(wide)

    return CombinedPredictionBundle(
        wide=wide.sort_values("composite_score", ascending=False).reset_index(drop=True),
        meta=meta_list,
        strategies=[],
        blend_weights=w,
        longshot_blend_weights=dict(DEFAULT_LONGSHOT_BLEND_WEIGHTS),
    )


def build_bundle(
    predictions_dir: Path | None = None,
    *,
    blend_weights: dict[str, float] | None = None,
    longshot_blend_weights: dict[str, float] | None = None,
) -> CombinedPredictionBundle:
    """
    Load blend prediction CSVs and merge on ``horse_name``.

    Prefers the six-file layout ``predictions_{target}.csv`` (+ optional ``.meta.json``).
    Falls back to legacy per-model Derby globs when simple files are absent.
    """
    root = predictions_dir or default_predictions_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"predictions directory not found: {root}")

    if _simple_blend_files_present(root):
        logger.info("Loading six blend CSVs from %s", root)
        return _build_simple_bundle(
            root,
            blend_weights=blend_weights,
            longshot_blend_weights=longshot_blend_weights,
        )

    logger.info("No simple blend files; trying legacy per-model CSV layout under %s", root)
    return _build_legacy_bundle(root, blend_weights=blend_weights)


def bundle_to_json(bundle: CombinedPredictionBundle, indent: int | None = 2) -> str:
    payload = bundle.to_json_payload()
    return json.dumps(payload, indent=indent, allow_nan=False)
