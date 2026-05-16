"""Deprecated: use :mod:`pim_results` and Brisnet ``.RES`` files instead of reference CSVs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pim_results import merge_official_pim_results


def load_preakness_results_table(path: str | Path) -> pd.DataFrame:
    raise NotImplementedError(
        "Reference CSVs are retired; use data/raw/results/*.RES via pim_results.load_results_directory."
    )


def merge_official_preakness_results(
    df: pd.DataFrame,
    reference: Path | pd.DataFrame,
    *,
    copy: bool = True,
    warn_name_mismatches: bool = True,
) -> pd.DataFrame:
    """Backward-compatible alias — *reference* must be a ``.RES`` directory path."""
    if isinstance(reference, (str, Path)) and Path(reference).is_dir():
        return merge_official_pim_results(
            df, reference, copy=copy, warn_name_mismatches=warn_name_mismatches
        )
    raise NotImplementedError(
        "Pass a results directory (data/raw/results), not a reference CSV."
    )
