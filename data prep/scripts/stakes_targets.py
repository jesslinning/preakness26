"""Extra stake targets from official finish plus within-field morning-line context.

Requires ``finalize_derby_training_columns`` then ``add_field_relative_features`` so that
``morn_line_implied_prob_field_rank`` exists (Brisnet ``rank(..., method="min")`` on implied
prob within each race: ties share the best rank in the tie band, e.g. co-third favorites are
both rank 3).
"""

from __future__ import annotations

import pandas as pd

_GROUP_KEYS = ("track", "date", "race")


def add_stakes_extras_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Add ML-beat and long-shot-style targets after field-relative morning-line features.

    - ``target_ml_rank_minus_finish``: ``morn_line_implied_prob_field_rank - target_FP``
      (positive ⇒ finished better than ML ordering).
    - ``target_top5_ml_rank_gt4``: ``target_top5`` == 1 and ML field rank ``> 4``.
    - ``target_deep_closer_top5``: ``target_top5`` == 1 and ML field rank ``>= 4``.
    """
    need = (
        "target_FP",
        "target_top5",
        "morn_line_implied_prob_field_rank",
    )
    if any(c not in df.columns for c in need):
        return df

    out = df.copy()
    ml_rank = pd.to_numeric(out["morn_line_implied_prob_field_rank"], errors="coerce")
    fp = pd.to_numeric(out["target_FP"], errors="coerce")
    t5 = pd.to_numeric(out["target_top5"], errors="coerce")

    out["target_ml_rank_minus_finish"] = ml_rank - fp
    out["target_top5_ml_rank_gt4"] = ((ml_rank > 4) & (t5 == 1)).fillna(False).astype(int)
    out["target_deep_closer_top5"] = ((ml_rank >= 4) & (t5 == 1)).fillna(False).astype(int)

    return out
