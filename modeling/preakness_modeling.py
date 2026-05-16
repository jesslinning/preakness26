#!/usr/bin/env python3
"""
Preakness Stakes — DataRobot pipeline (idempotent Use Case, dataset, seven projects).

Phase A0: After the AI Catalog ``Dataset`` is ready, wait for dataset-scoped ``Informative Features``,
then create one idempotent **dataset (catalog)** predictor featurelist (Informative column names minus all
targets and ``official_final_odds``). Each modeling **project** gets a matching **project-scoped**
predictor featurelist (same name/columns; DataRobot uses a different id than the catalog).

Phase A1: Per target — create/get the project from the dataset, ``MANUAL`` to register the target.

Phase A2: Parallel ``start_autopilot(..., QUICK)`` on each project's predictor featurelist id with
``worker_count=-1`` (SDK sets workers on the project before autopilot).

Phase B: Recommended → parent → feature impact → FI top-100 → first Comprehensive → wait.

Phase C: Forced second Comprehensive on the same FI top-100 featurelist → wait.

Phase D: Delete Eureqa leaderboard models whose ``model_type`` lists **40, 250, or 1000**
generations (not 10000 or other counts).

Phase E: Average blend (``BLENDER_METHOD.AVERAGE``) of the top five non-blender models by CV.

Phase F: Batch-score each average blend on ``data/processed/predictions.csv`` →
``data prep/data/predictions/predictions_{target}.csv`` plus ``predictions_{target}.meta.json``
(child models for UI). Set ``PRK_BATCH_SCORING_ONLY=1`` to run Phase F only.

When the training CSV cannot satisfy DataRobot classification limits, the script sets
``target_type=Regression`` for affected 0/1 targets so modeling can proceed (predictions stay in
``[0, 1]``; leaderboard metrics are regression-style):

- Fewer than 100 rows (binary classification row minimum).
- Minority class count below 20 (binary classification class minimum).

Credentials: modeling/.env. Data: ../data prep/data/processed/combined.csv

Dependencies: from this directory run ``sh install_deps.sh`` (uses ``python3 -m venv`` and
``.venv/bin/python -m pip`` so a global ``pip`` command is not required).

Env: ``PRK_FORCE_NEW_FI_TOP100`` (same idea as ``KY_FORCE_NEW_FI_TOP100`` on the Derby script).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import datarobot as dr
import datarobot.errors as dre
import pandas as pd
from datarobot.enums import AUTOPILOT_MODE, BLENDER_METHOD, PROJECT_STAGE, TARGET_TYPE
from datarobot.models import FrozenModel
from datarobot.models.featurelist import DatasetFeaturelist
from datarobot.models.batch_job import IntakeAdapters, OutputAdapters
from datarobot.models.modeljob import ModelJob
from datarobot.models.recommended_model import ModelRecommendation
from datarobotx.idp.common.hashing import get_hash
from datarobotx.idp.datasets import get_or_create_dataset_from_file
from datarobotx.idp.projects import get_or_create_project_from_dataset
from datarobotx.idp.use_cases import get_or_create_use_case
from dotenv import load_dotenv

USE_CASE_NAME = "Preakness Stakes modeling"
USE_CASE_DESCRIPTION = "Preakness Stakes — preakness_modeling.py idempotent pipeline"
DATASET_NAME = "Preakness Stakes combined"

TARGETS = (
    "target_FP",
    "target_top3",
    "target_top5",
    "target_ml_rank_minus_finish",
    "target_top5_ml_rank_gt4",
    "target_deep_closer_top5",
)
EXCLUDED_TARGETS = TARGETS
EXTRA_PREDICTOR_EXCLUSIONS = ("official_final_odds",)
PREDICTOR_EXCLUSIONS = EXCLUDED_TARGETS + EXTRA_PREDICTOR_EXCLUSIONS

INFORMATIVE_FEATURES = "Informative Features"
PREDICTOR_FL_PREFIX = "Preakness predictors"
FI_TOP100_PREFIX = "FI top100"

# Idempotent name token: Informative base + exclusions (aligned with Derby ky_modeling pattern).
PREDICTOR_FL_TOKEN = get_hash("Informative", *sorted(PREDICTOR_EXCLUSIONS))

TOP_MODELS_PER_PROJECT = 5

PREDICTIONS_INTAKE_DATASET_NAME = "Preakness Stakes predictions 2026"
BLEND_MODEL_LABEL = "Average Blend (top 5 CV)"
BATCH_PASSTHROUGH_COLUMNS_DEFAULT = (
    "horse_name",
    "program_number",
    "morn_line_implied_prob_field_rank",
)

# DataRobot rejects binary classification below these limits (SaaS defaults).
DATAROBOT_CLASSIFICATION_MIN_ROWS = 100
DATAROBOT_CLASSIFICATION_MIN_MINORITY = 20

# 0/1 targets: use ``TARGET_TYPE.REGRESSION`` when limits above cannot be met.
TARGETS_BINARY = frozenset(
    {
        "target_top3",
        "target_top5",
        "target_top5_ml_rank_gt4",
        "target_deep_closer_top5",
    }
)

# Eureqa models to remove after the second Comprehensive: these generation counts only
# (parses ``N Generations`` / ``Instant Search: N Generations``; ``10000`` is not matched alone).
_EUREQA_DELETE_GENERATION_COUNTS = frozenset((40, 250, 1000))
_EUREQA_GEN_NUM = re.compile(r"(?i)(\d+)\s*(?:generations|gen)\b")

logger = logging.getLogger("preakness_modeling")


class _FlushStreamHandler(logging.StreamHandler):
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def _configure_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    h = _FlushStreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(h)
    logger.propagate = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _combined_csv_path() -> Path:
    return _repo_root() / "data prep" / "data" / "processed" / "combined.csv"


def _count_csv_data_rows(csv_path: Path) -> int:
    """Number of data rows (excluding header) in the training CSV."""
    with csv_path.open(encoding="utf-8", newline="") as f:
        n = sum(1 for _ in f)
    return max(0, n - 1)


def _binary_positive_counts(csv_path: Path) -> dict[str, int]:
    """Positive-class (1) counts per binary target column in the training CSV."""
    counts: dict[str, int] = {t: 0 for t in TARGETS_BINARY}
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for target in TARGETS_BINARY:
                val = row.get(target, "")
                if val in ("1", "1.0", "True", "true"):
                    counts[target] += 1
    return counts


def _binary_regression_reason(
    target: str,
    training_rows: int,
    positive_counts: dict[str, int],
) -> str | None:
    """Human-readable reason to use regression instead of binary classification, if any."""
    if target not in TARGETS_BINARY:
        return None
    if training_rows < DATAROBOT_CLASSIFICATION_MIN_ROWS:
        return (
            f"{training_rows} rows < {DATAROBOT_CLASSIFICATION_MIN_ROWS} DR classification minimum"
        )
    pos = positive_counts.get(target, 0)
    neg = training_rows - pos
    minority = min(pos, neg)
    if minority < DATAROBOT_CLASSIFICATION_MIN_MINORITY:
        return (
            f"minority class {minority} < {DATAROBOT_CLASSIFICATION_MIN_MINORITY} DR minimum "
            f"(pos={pos} neg={neg})"
        )
    return None


def _aim_target_type(
    target: str,
    training_rows: int,
    positive_counts: dict[str, int],
) -> str | None:
    """Return ``TARGET_TYPE.REGRESSION`` when DataRobot binary classification limits cannot be met."""
    reason = _binary_regression_reason(target, training_rows, positive_counts)
    if reason is None:
        return None
    logger.info("    target_type=REGRESSION for %r (%s)", target, reason)
    return TARGET_TYPE.REGRESSION


def _load_env() -> tuple[str, str]:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    try:
        token = os.environ["DATAROBOT_API_TOKEN"]
        endpoint = os.environ["DATAROBOT_ENDPOINT"]
    except KeyError as e:
        raise SystemExit(
            f"Missing env var {e!s}. Set DATAROBOT_API_TOKEN and DATAROBOT_ENDPOINT in modeling/.env"
        ) from e
    return token, endpoint


def _log_dataset_featurelists(dataset_id: str) -> None:
    try:
        ds = dr.Dataset.get(dataset_id)
        flists = ds.get_featurelists()
        logger.info("  Dataset %r: %s featurelist(s) at catalog scope", dataset_id, len(flists))
        for fl in flists[:20]:
            logger.info("    - %r", fl.name)
        if len(flists) > 20:
            logger.info("    ... (%s more)", len(flists) - 20)
    except Exception as exc:
        logger.warning("  Could not list dataset featurelists: %s", exc)


def _register_manual_target(project: dr.Project, target: str, aim_target_type: str | None) -> bool:
    """Register target and run EDA (MANUAL). Returns False if MANUAL was skipped (project already ready)."""
    project.refresh()
    st = project.get_status()
    if st.get("stage") == PROJECT_STAGE.MODELING:
        logger.info("    Target stage already MODELING for %s; skipping MANUAL.", project.id)
        return False
    logger.info("    analyze_and_model MANUAL target=%r worker_count=-1 ...", target)
    project.analyze_and_model(
        target=target,
        mode=AUTOPILOT_MODE.MANUAL,
        worker_count=-1,
        max_wait=3600,
        **({"target_type": aim_target_type} if aim_target_type else {}),
    )
    return True


def _wait_dataset_informative_features(dataset_id: str, timeout_secs: int = 7200) -> None:
    """Poll until the catalog dataset exposes ``Informative Features``."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        ds = dr.Dataset.get(dataset_id)
        for fl in ds.get_featurelists():
            if fl.name == INFORMATIVE_FEATURES:
                return
        logger.info("  Waiting for dataset %r to expose %r ...", dataset_id, INFORMATIVE_FEATURES)
        time.sleep(15)
    raise TimeoutError(
        f"Timed out waiting for dataset {dataset_id!r} to list {INFORMATIVE_FEATURES!r} in catalog featurelists"
    )


def _dataset_informative_feature_names(dataset_id: str) -> list[str]:
    """Raw feature names from the dataset's Informative Features list."""
    ds = dr.Dataset.get(dataset_id)
    for fl in ds.get_featurelists():
        if fl.name != INFORMATIVE_FEATURES:
            continue
        names = fl.features
        if not names:
            full = DatasetFeaturelist.get(dataset_id, fl.id)
            names = full.features
        if not names:
            raise RuntimeError(f"Dataset {dataset_id!r} Informative Features list has no feature names")
        return list(names)
    raise RuntimeError(f"Dataset {dataset_id!r} has no {INFORMATIVE_FEATURES!r} featurelist")


def _get_or_create_dataset_predictor_featurelist(dataset_id: str) -> DatasetFeaturelist:
    """Idempotent catalog featurelist: Informative minus ``PREDICTOR_EXCLUSIONS`` (explicit names)."""
    ds = dr.Dataset.get(dataset_id)
    label = f"{PREDICTOR_FL_PREFIX} [{PREDICTOR_FL_TOKEN}]"
    for fl in ds.get_featurelists():
        if not fl.name:
            continue
        if PREDICTOR_FL_TOKEN in fl.name and fl.name.startswith(PREDICTOR_FL_PREFIX):
            resolved = fl if fl.features else DatasetFeaturelist.get(dataset_id, fl.id)
            logger.info("  Reusing dataset predictor featurelist id=%s name=%r", resolved.id, resolved.name)
            return resolved

    informative = _dataset_informative_feature_names(dataset_id)
    exclude = set(PREDICTOR_EXCLUSIONS)
    predictor_cols = [n for n in informative if n not in exclude]
    logger.info(
        "  Creating dataset predictor FL %r — Informative=%s cols, after exclusions=%s",
        label,
        len(informative),
        len(predictor_cols),
    )
    return ds.create_featurelist(label, predictor_cols)


def _get_or_create_project_predictor_featurelist(
    project: dr.Project,
    dataset_id: str,
    dataset_predictor_featurelist_id: str,
    *,
    target: str,
) -> str:
    """Return the **project** featurelist id for the shared predictor set (not the catalog id).

    ``start_autopilot`` and modeling jobs require a project-scoped featurelist. The catalog id from
    ``Dataset.create_featurelist`` is not valid on the project API.
    """
    project.refresh()
    for fl in project.get_featurelists():
        if not fl.name:
            continue
        if PREDICTOR_FL_TOKEN in fl.name and fl.name.startswith(PREDICTOR_FL_PREFIX):
            fid = str(fl.id)
            logger.info(
                "  target=%r project=%s reuse project predictor FL id=%s name=%r",
                target,
                project.id,
                fid,
                fl.name,
            )
            return fid

    ds_fl = DatasetFeaturelist.get(dataset_id, dataset_predictor_featurelist_id)
    label = ds_fl.name or f"{PREDICTOR_FL_PREFIX} [{PREDICTOR_FL_TOKEN}]"
    feats = ds_fl.features
    if not feats:
        ds_fl = DatasetFeaturelist.get(dataset_id, dataset_predictor_featurelist_id)
        feats = ds_fl.features
    if not feats:
        raise RuntimeError(
            f"Dataset predictor featurelist {dataset_predictor_featurelist_id!r} has no feature names"
        )
    feat_list = list(feats)
    new_fl = project.create_featurelist(label, feat_list)
    logger.info(
        "  target=%r project=%s created project predictor FL id=%s name=%r (%s cols)",
        target,
        project.id,
        new_fl.id,
        label,
        len(feat_list),
    )
    return str(new_fl.id)


def _ensure_quick_with_predictor_fl(
    project: dr.Project,
    target: str,
    predictor_featurelist_id: str,
    aim_target_type: str | None,
    *,
    manual_ran: bool,
) -> None:
    """Run QUICK Autopilot on the **project** predictor featurelist (see
    :func:`_get_or_create_project_predictor_featurelist`).

    Phase A1 ``MANUAL`` runs ``analyze_and_model(..., MANUAL)``, which sets the target (and
    optional ``target_type``) via the AIM endpoint but does not start model autopilot. Calling
    ``analyze_and_model`` again for QUICK either repeats ``target`` (422: already selected) or
    omits it (422: target required) because the SDK always includes a ``target`` key in the AIM
    payload. Starting QUICK uses ``Project.start_autopilot(featurelist_id, mode=QUICK)`` instead,
    which only references the already-selected target.

    *aim_target_type* and *manual_ran* are unused but kept for caller symmetry with MANUAL.
    """
    _ = (aim_target_type, manual_ran)

    project.refresh()
    st = project.get_status()
    if st.get("autopilot_done"):
        logger.info("    Autopilot already completed for %s; skipping QUICK.", project.id)
        return
    if st.get("stage") == PROJECT_STAGE.MODELING and project.get_models():
        logger.info("    Project %s already has models; skipping QUICK.", project.id)
        return

    logger.info(
        "    start_autopilot QUICK logical_target=%r featurelist_id=%s (after MANUAL target registration) ...",
        target,
        predictor_featurelist_id,
    )
    project.set_worker_count(-1)
    project.start_autopilot(predictor_featurelist_id, mode=AUTOPILOT_MODE.QUICK)
    project.wait_for_autopilot(timeout=48 * 3600, verbosity=0)
    project.refresh()


def _unwrap_project_metrics_meta(meta: Any) -> list[dict[str, Any]]:
    if isinstance(meta, dict):
        return meta["metric_details"]
    return meta.metric_details


def _metric_is_ascending(project: dr.Project, metric_name: str) -> bool:
    project.refresh()
    tgt = project.target
    if not tgt:
        raise RuntimeError(f"Project {project.id} has no target")
    details = _unwrap_project_metrics_meta(project.get_metrics(tgt))
    for m in details:
        if m["metric_name"] == metric_name:
            return bool(m["ascending"])
    raise ValueError(f"Metric {metric_name!r} not found in project {project.id} metric_details")


def _cv_primary_score(model: dr.Model, metric: str) -> float | None:
    row = (model.metrics or {}).get(metric)
    if not row:
        return None
    for key in ("crossValidation", "backtesting", "validation"):
        v = row.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f):
            continue
        return f
    return None


def _is_blender_model(m: dr.Model) -> bool:
    mt = (getattr(m, "model_type", None) or "").lower()
    return "blend" in mt


def _top_models_by_cv(project_id: str, limit: int, *, exclude_blenders: bool = True) -> list[dr.Model]:
    project = dr.Project.get(project_id)
    project.refresh()
    metric = project.metric
    if not metric:
        raise RuntimeError(f"Project {project_id} has no optimization metric")

    is_ascending = _metric_is_ascending(project, metric)

    scored: list[tuple[float, str, dr.Model]] = []
    for m in dr.Model.list(project_id):
        if exclude_blenders and _is_blender_model(m):
            continue
        score = _cv_primary_score(m, metric)
        if score is None:
            continue
        scored.append((score, m.id, m))

    scored.sort(key=lambda x: (-x[0], x[1]) if not is_ascending else (x[0], x[1]))
    if not scored:
        return []

    refresh_n = min(len(scored), max(limit * 5, 25))
    fresh: list[tuple[float, str, dr.Model]] = []
    for _, mid, _ in scored[:refresh_n]:
        m = dr.Model.get(project_id, mid)
        if exclude_blenders and _is_blender_model(m):
            continue
        score = _cv_primary_score(m, metric)
        if score is None:
            continue
        fresh.append((score, m.id, m))
    fresh.sort(key=lambda x: (-x[0], x[1]) if not is_ascending else (x[0], x[1]))
    out_models = [t[2] for t in fresh[:limit]]

    if len(out_models) < limit:
        logger.warning(
            "  Only %s model(s) with CV scores for metric %r (wanted %s)",
            len(out_models),
            metric,
            limit,
        )
    return out_models


def _resolve_parent_for_feature_impact(project_id: str, model: dr.Model) -> dr.Model:
    if getattr(model, "is_frozen", False):
        fm = FrozenModel.get(project_id, model.id)
        pid = getattr(fm, "parent_model_id", None)
        if not pid:
            raise RuntimeError(f"Frozen model {model.id} has no parent_model_id")
        return dr.Model.get(project_id, pid)
    return model


def _request_feature_impact_subset(parents: list[tuple[dr.Project, dr.Model]]) -> None:
    def _request_one(item: tuple[dr.Project, dr.Model]) -> str:
        proj, parent = item
        logger.info("  request_feature_impact parent=%s project=%s", parent.id, proj.id)
        parent.request_feature_impact()
        return proj.id

    if not parents:
        return
    with ThreadPoolExecutor(max_workers=len(parents)) as ex:
        list(ex.map(_request_one, parents))


def _poll_feature_impact_until_ready(
    parents: list[tuple[dr.Project, dr.Model]],
    poll_secs: int = 60,
    timeout_secs: int = 48 * 3600,
    initial_results: dict[str, list[Any]] | None = None,
) -> dict[str, list[Any]]:
    deadline = time.time() + timeout_secs
    results: dict[str, list[Any]] = dict(initial_results or {})
    pending = {proj.id for proj, _ in parents if proj.id not in results}

    while time.time() < deadline and pending:
        for proj, parent in parents:
            if proj.id not in pending:
                continue
            try:
                fi = parent.get_feature_impact()
                results[proj.id] = fi
                pending.discard(proj.id)
                logger.info("    Feature impact ready for project %s", proj.id)
            except dre.ClientError as e:
                if e.status_code not in (404, 422):
                    raise
            except Exception:
                pass
        if pending:
            logger.info("  FI pending for %s project(s); sleeping %ss ...", len(pending), poll_secs)
            time.sleep(poll_secs)

    if pending:
        raise TimeoutError(f"Feature impact not ready for projects: {pending}")
    return results


def _top100_feature_names(fi_rows: list[Any]) -> list[str]:
    def norm(row: Any) -> float:
        if isinstance(row, dict):
            return float(row.get("impactNormalized") or row.get("impact_normalized") or 0)
        return float(
            getattr(row, "impact_normalized", None) or getattr(row, "impactNormalized", None) or 0
        )

    def fname(row: Any) -> str:
        if isinstance(row, dict):
            return str(row.get("featureName") or row.get("feature_name") or "")
        return str(getattr(row, "feature_name", None) or getattr(row, "featureName", None) or "")

    rows = list(fi_rows)
    rows.sort(key=lambda r: (-norm(r), fname(r)))
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        n = fname(row)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
        if len(out) >= 100:
            break
    return out


def _force_new_fi_top100_featurelist() -> bool:
    return os.environ.get("PRK_FORCE_NEW_FI_TOP100", "").strip().lower() in ("1", "true", "yes")


def _resolve_fi_top100_featurelist(
    project: dr.Project, parent_model_id: str, names: list[str]
) -> dr.Featurelist:
    project.refresh()
    fi_token = get_hash(parent_model_id, tuple(names))
    label = f"{FI_TOP100_PREFIX} [{fi_token}]"

    for fl in project.get_featurelists():
        if fi_token in fl.name and fl.name.startswith(FI_TOP100_PREFIX):
            logger.info("  Reusing FI top100 id=%s name=%r", fl.id, fl.name)
            return fl

    if not _force_new_fi_top100_featurelist():
        reuse_candidates = [
            fl
            for fl in project.get_featurelists()
            if fl.name.startswith(FI_TOP100_PREFIX)
            and _models_exist_for_featurelist(project.id, fl.id)
        ]
        if reuse_candidates:
            reuse_candidates.sort(key=lambda x: x.name)
            chosen = reuse_candidates[0]
            logger.info("  Reusing FI top100 with models id=%s name=%r", chosen.id, chosen.name)
            return chosen

    logger.info("  Creating FI top100 featurelist %r (%s features)", label, len(names))
    return project.create_featurelist(name=label, features=names)


def _models_exist_for_featurelist(project_id: str, featurelist_id: str) -> bool:
    for m in dr.Model.list(project_id):
        if getattr(m, "featurelist_id", None) == featurelist_id:
            return True
    return False


def _kickoff_comprehensive(
    project_id: str, fi_featurelist_id: str, target: str, *, force: bool = False
) -> bool:
    project = dr.Project.get(project_id)
    project.refresh()
    if not force and _models_exist_for_featurelist(project_id, fi_featurelist_id):
        logger.info(
            "[%s] Comprehensive skipped — leaderboard already has models for FI list %r",
            target,
            fi_featurelist_id,
        )
        return False
    logger.info("[%s] start_autopilot COMPREHENSIVE featurelist=%s (force=%s)", target, fi_featurelist_id, force)
    project.set_worker_count(-1)
    project.start_autopilot(fi_featurelist_id, mode=AUTOPILOT_MODE.COMPREHENSIVE)
    return True


def _wait_comprehensive_autopilot(project_ids: list[str]) -> None:
    def _wait_one(pid: str) -> str:
        logger.info("  Waiting for autopilot (Comprehensive): %s ...", pid)
        dr.Project.get(pid).wait_for_autopilot(timeout=72 * 3600, verbosity=0)
        return pid

    if not project_ids:
        return
    with ThreadPoolExecutor(max_workers=len(project_ids)) as ex:
        list(ex.map(_wait_one, project_ids))


def _kickoff_comprehensive_job(job: tuple[str, str, str, bool]) -> str | None:
    pid, fl_id, target, force = job
    return pid if _kickoff_comprehensive(pid, fl_id, target, force=force) else None


def _eureqa_250_or_1000_generations(model: dr.Model) -> bool:
    """True when this is a Eureqa model and ``model_type`` lists 40 / 250 / 1000 generations.

    Parses ``N Generations`` or abbreviated ``N gen`` (case-insensitive). Counts such as
    10000 are preserved because only 40, 250, and 1000 trigger deletion.
    """
    mt = getattr(model, "model_type", None) or ""
    if re.search(r"(?i)eureqa", mt) is None:
        return False
    gen_counts = [int(m.group(1)) for m in _EUREQA_GEN_NUM.finditer(mt)]
    return any(n in _EUREQA_DELETE_GENERATION_COUNTS for n in gen_counts)


def _delete_eureqa_250_1000_models(project_id: str, target: str) -> int:
    n = 0
    for m in dr.Model.list(project_id):
        if not _eureqa_250_or_1000_generations(m):
            continue
        try:
            full = dr.Model.get(project_id, m.id)
            logger.info("  [%s] Deleting Eureqa model id=%s type=%r", target, m.id, full.model_type)
            full.delete()
            n += 1
        except Exception as exc:
            logger.warning("  [%s] Failed to delete model %s: %s", target, m.id, exc)
    return n


def _average_blend_top5(project_id: str, target: str) -> str | None:
    top = _top_models_by_cv(project_id, TOP_MODELS_PER_PROJECT, exclude_blenders=True)
    if len(top) < 2:
        logger.warning("[%s] Need at least 2 models to blend; got %s", target, len(top))
        return None
    ids = [m.id for m in top]
    proj = dr.Project.get(project_id)
    logger.info("[%s] Creating average blend from model_ids=%s", target, ids)
    job = proj.blend(ids, BLENDER_METHOD.AVERAGE)
    job.wait_for_completion(max_wait=7200)

    blend = ModelJob.get_model(project_id, job.id)
    blend_id = blend.id if blend is not None else None
    logger.info("[%s] Average blend finished; blend_model_id=%r", target, blend_id)
    return str(blend_id) if blend_id else None


def _log_pipeline_summary(
    works: list[dict[str, Any]], *, use_case_id: str, dataset_id: str, predictor_dataset_fl_id: str
) -> None:
    logger.info("\n=== Summary ===")
    logger.info("use_case_id=%s", use_case_id)
    logger.info("dataset_id=%s", dataset_id)
    logger.info("dataset_predictor_featurelist_id=%s", predictor_dataset_fl_id)
    for w in works:
        n = len(list(dr.Model.list(w["project_id"])))
        logger.info("target=%r project_id=%s models=%s", w["target"], w["project_id"], n)


def _predictions_csv_path() -> Path:
    return _repo_root() / "data prep" / "data" / "processed" / "predictions.csv"


def _predictions_output_dir() -> Path:
    out = _repo_root() / "data prep" / "data" / "predictions"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _batch_scoring_only_mode() -> bool:
    v = os.environ.get("PRK_BATCH_SCORING_ONLY", "").strip().lower()
    return v in ("1", "true", "yes", "y")


def _batch_passthrough_columns() -> list[str]:
    raw = os.environ.get("PRK_BATCH_PASSTHROUGH_COLUMNS", "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(BATCH_PASSTHROUGH_COLUMNS_DEFAULT)


def _batch_force_rescore() -> bool:
    v = os.environ.get("PRK_BATCH_FORCE_RESCORE", "").strip().lower()
    return v in ("1", "true", "yes", "y")


def _batch_predict_download_timeout() -> int:
    return int(os.environ.get("PRK_BATCH_PREDICT_DOWNLOAD_TIMEOUT", "3600"))


def _batch_predict_download_read_timeout() -> int:
    return int(os.environ.get("PRK_BATCH_PREDICT_DOWNLOAD_READ_TIMEOUT", "7200"))


def _predictions_intake_csv() -> Path:
    override = os.environ.get("PRK_PREDICTIONS_INTAKE_CSV", "").strip()
    if override:
        p = Path(override)
        if not p.is_file():
            raise FileNotFoundError(f"PRK_PREDICTIONS_INTAKE_CSV not found: {p}")
        return p.resolve()
    p = _predictions_csv_path()
    if not p.is_file():
        raise FileNotFoundError(
            f"Predictions intake not found: {p}. "
            "Run: cd 'data prep' && python scripts/process_raw_drfs.py "
            "--predictions-only --prediction-drf 2026/PRK0516-2026.DRF"
        )
    return p


def _prediction_output_basename(target: str) -> str:
    return f"predictions_{target}.csv"


def _prediction_meta_basename(target: str) -> str:
    return f"predictions_{target}.meta.json"


def _prediction_value_column(target: str) -> str:
    if target in ("target_FP", "target_ml_rank_minus_finish"):
        return f"{target}_PREDICTION"
    if target in TARGETS_BINARY:
        return f"{target}_1_PREDICTION"
    raise ValueError(f"unknown target {target!r}")


def _find_prediction_column(df: Any, target: str) -> str:
    preferred = _prediction_value_column(target)
    if preferred in df.columns:
        return preferred
    suffix = f"{target}_PREDICTION"
    for c in df.columns:
        if c == suffix or (c.startswith(f"{target}_") and c.endswith("_PREDICTION")):
            return c
    raise KeyError(
        f"No prediction column for {target!r} in batch output; sample columns: {list(df.columns)[:25]}"
    )


def _find_average_blend_model(project_id: str) -> dr.Model:
    blenders: list[dr.Model] = []
    for m in dr.Model.list(project_id):
        if not _is_blender_model(m):
            continue
        blenders.append(dr.Model.get(project_id, m.id))
    if not blenders:
        raise RuntimeError(f"No average blend model on project {project_id}")
    for b in blenders:
        mt = (getattr(b, "model_type", None) or "").lower()
        if "average" in mt:
            return b
    return blenders[0]


def _child_models_for_meta(project_id: str) -> list[dict[str, Any]]:
    project = dr.Project.get(project_id)
    project.refresh()
    metric = project.metric
    if not metric:
        raise RuntimeError(f"Project {project_id} has no optimization metric")
    top = _top_models_by_cv(project_id, TOP_MODELS_PER_PROJECT, exclude_blenders=True)
    children: list[dict[str, Any]] = []
    for m in top:
        full = dr.Model.get(project_id, m.id)
        children.append(
            {
                "model_id": full.id,
                "model_label": getattr(full, "model_type", None) or full.id,
                "cv_score": _cv_primary_score(full, metric),
            }
        )
    return children


def _write_blend_meta(
    out_dir: Path,
    *,
    target: str,
    blend: dr.Model,
    child_models: list[dict[str, Any]],
    prediction_csv: Path,
) -> Path:
    payload = {
        "target": target,
        "blend_model_id": blend.id,
        "blend_model_label": BLEND_MODEL_LABEL,
        "blend_model_type": getattr(blend, "model_type", None),
        "prediction_path": str(prediction_csv),
        "child_models": child_models,
    }
    meta_path = out_dir / _prediction_meta_basename(target)
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return meta_path


def _finalize_blend_csv(raw_path: Path, *, target: str, passthrough: list[str]) -> pd.DataFrame:
    df = pd.read_csv(raw_path)
    pred_col = _find_prediction_column(df, target)
    keep = [c for c in passthrough if c in df.columns]
    if pred_col not in keep:
        keep.append(pred_col)
    out = df[keep].copy()
    expected = _prediction_value_column(target)
    if pred_col != expected:
        out = out.rename(columns={pred_col: expected})
    return out


def _score_blend_for_target(
    work: dict[str, Any],
    *,
    intake_dataset_id: str,
) -> tuple[Path, Path]:
    target = work["target"]
    project_id = work["project_id"]
    out_dir = _predictions_output_dir()
    out_path = out_dir / _prediction_output_basename(target)
    raw_path = out_dir / f".{target}.batch_raw.csv"
    meta_path = out_dir / _prediction_meta_basename(target)

    if out_path.is_file() and not _batch_force_rescore():
        logger.info("  Skip (exists) target=%r → %s", target, out_path)
        if not meta_path.is_file():
            blend = _find_average_blend_model(project_id)
            _write_blend_meta(
                out_dir,
                target=target,
                blend=blend,
                child_models=_child_models_for_meta(project_id),
                prediction_csv=out_path,
            )
        return out_path, meta_path

    blend = _find_average_blend_model(project_id)
    children = _child_models_for_meta(project_id)
    passthrough = _batch_passthrough_columns()
    catalog = dr.Dataset.get(intake_dataset_id)

    logger.info(
        "  Batch scoring target=%r blend=%s type=%r → %s",
        target,
        blend.id,
        getattr(blend, "model_type", ""),
        out_path,
    )

    dr.BatchPredictionJob.score_with_leaderboard_model(
        blend,
        intake_settings={
            "type": IntakeAdapters.DATASET,
            "dataset": catalog,
        },
        output_settings={
            "type": OutputAdapters.LOCAL_FILE,
            "path": str(raw_path),
        },
        passthrough_columns=passthrough,
        download_timeout=_batch_predict_download_timeout(),
        download_read_timeout=_batch_predict_download_read_timeout(),
    )

    slim = _finalize_blend_csv(raw_path, target=target, passthrough=passthrough)
    slim.to_csv(out_path, index=False, encoding="utf-8")
    if raw_path.is_file():
        raw_path.unlink()

    _write_blend_meta(
        out_dir,
        target=target,
        blend=blend,
        child_models=children,
        prediction_csv=out_path,
    )
    logger.info("  Wrote %s rows → %s (%s child models in meta)", len(slim), out_path, len(children))
    return out_path, meta_path


def _phase_f_batch_blend_predictions(
    works: list[dict[str, Any]],
    *,
    endpoint: str,
    token: str,
    use_case_id: str,
) -> None:
    intake_csv = _predictions_intake_csv()
    logger.info("\n=== Phase F: batch blend predictions ===")
    logger.info("  Intake CSV: %s", intake_csv)
    intake_id = get_or_create_dataset_from_file(
        endpoint,
        token,
        PREDICTIONS_INTAKE_DATASET_NAME,
        str(intake_csv),
        use_cases=use_case_id,
    )
    logger.info("  Intake dataset id=%s", intake_id)
    logger.info(
        "  Passthrough=%s force_rescore=%s output_dir=%s",
        _batch_passthrough_columns(),
        _batch_force_rescore(),
        _predictions_output_dir(),
    )

    for w in works:
        _score_blend_for_target(w, intake_dataset_id=intake_id)


def _works_for_batch_scoring(
    endpoint: str,
    token: str,
    use_case_id: str,
    dataset_id: str,
) -> list[dict[str, Any]]:
    raw_ids = os.environ.get("PRK_PREDICTIONS_PROJECT_IDS", "").strip()
    if raw_ids:
        ids = [x.strip() for x in raw_ids.split(",") if x.strip()]
        if len(ids) != len(TARGETS):
            raise SystemExit(
                f"PRK_PREDICTIONS_PROJECT_IDS must have {len(TARGETS)} ids for {TARGETS}"
            )
        return [{"target": t, "project_id": pid} for t, pid in zip(TARGETS, ids, strict=True)]

    works: list[dict[str, Any]] = []
    for target in TARGETS:
        prep_token = get_hash(dataset_id, use_case_id, "preakness2026_modeling", target)
        project_label = f"Preakness Stakes modeling — {target} [{prep_token}]"
        project_id = get_or_create_project_from_dataset(
            endpoint,
            token,
            project_label,
            dataset_id,
            use_case=use_case_id,
        )
        works.append({"target": target, "project_id": project_id})
    return works


def _run_quick_job(args: tuple[str, str, str, str | None, bool]) -> None:
    """project_id, target, predictor_project_featurelist_id, aim_target_type, manual_ran."""
    pid, target, fl_id, aim_target_type, manual_ran = args
    project = dr.Project.get(pid)
    _ensure_quick_with_predictor_fl(project, target, fl_id, aim_target_type, manual_ran=manual_ran)


def main() -> None:
    _configure_logging()
    token, endpoint = _load_env()
    dr.Client(token=token, endpoint=endpoint)

    if _batch_scoring_only_mode():
        csv_path = _combined_csv_path()
        if not csv_path.is_file():
            raise SystemExit(f"Data file not found (for project lookup): {csv_path}")
        use_case_id = get_or_create_use_case(endpoint, token, USE_CASE_NAME, USE_CASE_DESCRIPTION)
        dataset_id = get_or_create_dataset_from_file(
            endpoint,
            token,
            DATASET_NAME,
            str(csv_path),
            use_cases=use_case_id,
        )
        works = _works_for_batch_scoring(endpoint, token, use_case_id, dataset_id)
        _phase_f_batch_blend_predictions(works, endpoint=endpoint, token=token, use_case_id=use_case_id)
        logger.info("\n=== Summary (batch scoring only) ===")
        for w in works:
            p = _predictions_output_dir() / _prediction_output_basename(w["target"])
            logger.info("  target=%r → %s", w["target"], p)
        return

    csv_path = _combined_csv_path()
    if not csv_path.is_file():
        raise SystemExit(f"Data file not found: {csv_path}")

    training_rows = _count_csv_data_rows(csv_path)
    positive_counts = _binary_positive_counts(csv_path)
    logger.info("Training CSV data rows (excl. header): %s", training_rows)
    for t in sorted(TARGETS_BINARY):
        pos = positive_counts[t]
        neg = training_rows - pos
        logger.info("  %s: pos=%s neg=%s minority=%s", t, pos, neg, min(pos, neg))
    regression_binary = sorted(
        t for t in TARGETS_BINARY if _binary_regression_reason(t, training_rows, positive_counts)
    )
    if regression_binary:
        logger.warning(
            "Binary targets modeled as regression (DR limits): %s",
            regression_binary,
        )

    logger.info(
        "Predictor featurelists will be Informative minus %s exclusion(s): %s",
        len(PREDICTOR_EXCLUSIONS),
        PREDICTOR_EXCLUSIONS,
    )

    logger.info("Use case...")
    use_case_id = get_or_create_use_case(endpoint, token, USE_CASE_NAME, USE_CASE_DESCRIPTION)
    logger.info("  id=%s", use_case_id)

    logger.info("Dataset (idempotent upload)...")
    dataset_id = get_or_create_dataset_from_file(
        endpoint,
        token,
        DATASET_NAME,
        str(csv_path),
        use_cases=use_case_id,
    )
    logger.info("  id=%s", dataset_id)
    _wait_dataset_informative_features(dataset_id)
    predictor_ds_fl = _get_or_create_dataset_predictor_featurelist(dataset_id)
    predictor_dataset_fl_id = str(predictor_ds_fl.id)
    logger.info("  Shared dataset predictor featurelist id=%s name=%r", predictor_dataset_fl_id, predictor_ds_fl.name)
    _log_dataset_featurelists(dataset_id)

    works: list[dict[str, Any]] = []
    for target in TARGETS:
        logger.info("\n=== Phase A1: project + MANUAL target=%r ===", target)
        prep_token = get_hash(dataset_id, use_case_id, "preakness2026_modeling", target)
        project_label = f"Preakness Stakes modeling — {target} [{prep_token}]"
        project_id = get_or_create_project_from_dataset(
            endpoint,
            token,
            project_label,
            dataset_id,
            use_case=use_case_id,
        )
        logger.info("  project_id=%s name=%r", project_id, project_label)
        project = dr.Project.get(project_id)
        aim_tt = _aim_target_type(target, training_rows, positive_counts)
        manual_ran = _register_manual_target(project, target, aim_tt)
        predictor_project_fl_id = _get_or_create_project_predictor_featurelist(
            project,
            dataset_id,
            predictor_dataset_fl_id,
            target=target,
        )
        works.append(
            {
                "target": target,
                "project_id": project_id,
                "predictor_project_fl_id": predictor_project_fl_id,
                "predictor_dataset_fl_id": predictor_dataset_fl_id,
                "aim_target_type": aim_tt,
                "manual_ran": manual_ran,
            }
        )

    logger.info("\n=== Phase A2: parallel QUICK analyze_and_model (one per target) ===")
    n_workers = max(1, len(works))
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        jobs = [
            (
                w["project_id"],
                w["target"],
                w["predictor_project_fl_id"],
                w["aim_target_type"],
                w["manual_ran"],
            )
            for w in works
        ]
        list(ex.map(_run_quick_job, jobs))

    logger.info("\n=== Phase B: FI / Comprehensive (first pass) ===")
    parents: list[tuple[dr.Project, dr.Model]] = []
    for w in works:
        proj = dr.Project.get(w["project_id"])
        rec = ModelRecommendation.get(proj.id)
        if rec is None:
            raise RuntimeError(f"No recommended model for project {proj.id}")
        m = rec.get_model()
        parent = _resolve_parent_for_feature_impact(proj.id, m)
        parents.append((proj, parent))
        logger.info(
            "  target=%r recommended=%s frozen=%s fi_model=%s",
            w["target"],
            m.id,
            getattr(m, "is_frozen", False),
            parent.id,
        )

    fi_prefetch: dict[str, list[Any]] = {}
    fi_need_request: list[tuple[dr.Project, dr.Model]] = []
    for proj, parent in parents:
        try:
            fi_prefetch[proj.id] = parent.get_feature_impact()
            logger.info("    Feature impact already available for project %s", proj.id)
        except dre.ClientError as e:
            if e.status_code in (404, 422):
                fi_need_request.append((proj, parent))
            else:
                raise

    if fi_need_request:
        logger.info("  Requesting feature impact for %s project(s) ...", len(fi_need_request))
        _request_feature_impact_subset(fi_need_request)

    fi_results = _poll_feature_impact_until_ready(parents, initial_results=fi_prefetch)

    comprehensive_jobs: list[tuple[str, str, str, bool]] = []
    for w in works:
        proj = dr.Project.get(w["project_id"])
        fi_rows = fi_results[proj.id]
        names = _top100_feature_names(fi_rows)
        rec = ModelRecommendation.get(proj.id)
        parent = _resolve_parent_for_feature_impact(proj.id, rec.get_model())
        fi_fl = _resolve_fi_top100_featurelist(proj, parent.id, names)
        w["fi_top100_fl_id"] = fi_fl.id
        logger.info("  target=%r FI top100 fl=%r (%s features)", w["target"], fi_fl.id, len(names))
        comprehensive_jobs.append((proj.id, fi_fl.id, w["target"], False))

    logger.info("\n=== Phase B2: Comprehensive kickoff (first, parallel) ===")
    pending: list[str] = []
    if comprehensive_jobs:
        with ThreadPoolExecutor(max_workers=len(comprehensive_jobs)) as ex:
            kick_results = list(ex.map(_kickoff_comprehensive_job, comprehensive_jobs))
        pending = [r for r in kick_results if r]

    if comprehensive_jobs and not pending:
        logger.info("  All first Comprehensive runs skipped (models already exist for FI top100).")

    if pending:
        logger.info("\n=== Phase B3: wait first Comprehensive ===")
        _wait_comprehensive_autopilot(pending)

    logger.info("\n=== Phase C2: Comprehensive second pass (forced, parallel) ===")
    second_jobs = [(w["project_id"], w["fi_top100_fl_id"], w["target"], True) for w in works]
    pending2: list[str] = []
    with ThreadPoolExecutor(max_workers=len(second_jobs)) as ex:
        kick2 = list(ex.map(_kickoff_comprehensive_job, second_jobs))
    pending2 = [r for r in kick2 if r]
    if pending2:
        logger.info("\n=== Phase C3: wait second Comprehensive ===")
        _wait_comprehensive_autopilot(pending2)

    logger.info("\n=== Phase D: delete Eureqa 250/1000 generation models ===")
    for w in works:
        deleted = _delete_eureqa_250_1000_models(w["project_id"], w["target"])
        logger.info("  [%s] deleted %s Eureqa model(s)", w["target"], deleted)

    logger.info("\n=== Phase E: average blend top %s ===", TOP_MODELS_PER_PROJECT)
    for w in works:
        bid = _average_blend_top5(w["project_id"], w["target"])
        w["average_blend_model_id"] = bid

    _phase_f_batch_blend_predictions(works, endpoint=endpoint, token=token, use_case_id=use_case_id)

    _log_pipeline_summary(works, use_case_id=use_case_id, dataset_id=dataset_id, predictor_dataset_fl_id=predictor_dataset_fl_id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger("preakness_modeling").warning("Interrupted")
        sys.exit(130)
