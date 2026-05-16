"""
Scenario helpers for ordered exotic bets. Uses marginal scores only; joint estimates are
**illustrative** (naive conditional softmax), not track-calibrated probabilities.

All entrypoints return JSON-serializable dicts for a future web UI.
"""

from __future__ import annotations

import itertools
from typing import Any, Literal

import numpy as np
import pandas as pd

RankingPreset = Literal[
    "composite",
    "longshot_index",
    "ensemble_top3",
    "ensemble_top5",
    "fp_strength",
]


def _scores_for_preset(df: pd.DataFrame, preset: RankingPreset) -> pd.Series:
    if preset == "composite":
        return df["composite_score"]
    if preset == "longshot_index":
        return df["longshot_index"]
    if preset == "ensemble_top3":
        return df["ensemble_top3"]
    if preset == "ensemble_top5":
        return df["ensemble_top5"]
    if preset == "fp_strength":
        return df["fp_strength"]
    raise ValueError(f"unknown preset {preset!r}")


def _score_column(preset: RankingPreset) -> str:
    return {
        "composite": "composite_score",
        "longshot_index": "longshot_index",
        "ensemble_top3": "ensemble_top3",
        "ensemble_top5": "ensemble_top5",
        "fp_strength": "fp_strength",
    }[preset]


def ranking_table(
    bundle_wide: pd.DataFrame,
    preset: RankingPreset = "composite",
) -> dict[str, Any]:
    """Ordered list of horses by preset score (descending)."""
    s = _scores_for_preset(bundle_wide, preset)
    order = np.argsort(-s.values)
    names = bundle_wide["horse_name"].values
    scores = s.values
    rows = []
    for rank, i in enumerate(order, start=1):
        val = scores[i]
        rows.append(
            {
                "rank": rank,
                "horse_name": str(names[i]),
                "score": None if pd.isna(val) else float(val),
                "preset": preset,
            }
        )
    return {"preset": preset, "ranking": rows}


def _softmax(logits: np.ndarray) -> np.ndarray:
    z = logits - np.max(logits)
    e = np.exp(np.clip(z, -80, 80))
    return e / e.sum()


def _probs_remaining(
    bundle_wide: pd.DataFrame,
    preset: RankingPreset,
    exclude_indices: set[int],
) -> np.ndarray:
    """Softmax over horses not in exclude_indices."""
    s = _scores_for_preset(bundle_wide, preset).astype(float).values.copy()
    for i in exclude_indices:
        s[i] = -1e18
    return _softmax(s)


def _ordered_finish_naive_prob(
    bundle_wide: pd.DataFrame,
    preset: RankingPreset,
    horse_indices: list[int],
) -> float:
    """P(order) as chained softmax picks (illustrative)."""
    naive = 1.0
    exclude: set[int] = set()
    for idx in horse_indices:
        p = _probs_remaining(bundle_wide, preset, exclude)
        naive *= float(p[idx])
        exclude.add(idx)
    return naive


def exacta_scenario(
    bundle_wide: pd.DataFrame,
    *,
    preset: RankingPreset = "composite",
    top_n: int = 8,
    max_tickets: int = 56,
    cost_per_ticket: float = 1.0,
    payout_if_win: float | None = None,
) -> dict[str, Any]:
    return _scenario_k(
        bundle_wide,
        k=2,
        bet_label="exacta",
        preset=preset,
        top_n=top_n,
        max_tickets=max_tickets,
        cost_per_ticket=cost_per_ticket,
        payout_if_win=payout_if_win,
    )


def _scenario_k(
    bundle_wide: pd.DataFrame,
    *,
    k: int,
    bet_label: str,
    preset: RankingPreset,
    top_n: int,
    max_tickets: int,
    cost_per_ticket: float,
    payout_if_win: float | None,
) -> dict[str, Any]:
    col = _score_column(preset)
    df = bundle_wide.sort_values(by=col, ascending=False).head(top_n)
    horses_subset = df["horse_name"].tolist()
    idx_map = {h: i for i, h in enumerate(bundle_wide["horse_name"].tolist())}

    keys_by_k = {
        2: ("first", "second"),
        3: ("first", "second", "third"),
        4: ("first", "second", "third", "fourth"),
    }
    keys = keys_by_k[k]

    tickets: list[dict[str, Any]] = []
    for perm in itertools.permutations(horses_subset, k):
        idxs = [idx_map[h] for h in perm]
        naive = _ordered_finish_naive_prob(bundle_wide, preset, idxs)
        row = {keys[m]: perm[m] for m in range(k)}
        row["naive_probability"] = float(naive)
        row["note"] = "illustrative chained softmax — not calibrated track probability"
        if payout_if_win is not None:
            row["expected_value_per_dollar_stake"] = float(
                naive * payout_if_win - cost_per_ticket
            )
        tickets.append(row)

    tickets.sort(key=lambda r: r["naive_probability"], reverse=True)
    if max_tickets > 0:
        tickets = tickets[:max_tickets]

    total_cost = len(tickets) * cost_per_ticket
    return {
        "bet_type": bet_label,
        "preset": preset,
        "top_n": top_n,
        "cost_per_ticket": cost_per_ticket,
        "ticket_count": len(tickets),
        "total_cost": total_cost,
        "tickets": tickets,
    }


def trifecta_scenario(
    bundle_wide: pd.DataFrame,
    *,
    preset: RankingPreset = "composite",
    top_n: int = 10,
    max_tickets: int = 120,
    cost_per_ticket: float = 0.5,
    payout_if_win: float | None = None,
) -> dict[str, Any]:
    return _scenario_k(
        bundle_wide,
        k=3,
        bet_label="trifecta",
        preset=preset,
        top_n=top_n,
        max_tickets=max_tickets,
        cost_per_ticket=cost_per_ticket,
        payout_if_win=payout_if_win,
    )


def superfecta_scenario(
    bundle_wide: pd.DataFrame,
    *,
    preset: RankingPreset = "composite",
    top_n: int = 10,
    max_tickets: int = 200,
    cost_per_ticket: float = 0.1,
    payout_if_win: float | None = None,
) -> dict[str, Any]:
    return _scenario_k(
        bundle_wide,
        k=4,
        bet_label="superfecta",
        preset=preset,
        top_n=top_n,
        max_tickets=max_tickets,
        cost_per_ticket=cost_per_ticket,
        payout_if_win=payout_if_win,
    )
