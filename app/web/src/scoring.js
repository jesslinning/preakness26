/** Nested α (market) then β (longshot) blend helpers. */

export function clamp01(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

/** Expanded weights for display readout. */
export function blendWeights(alpha, beta) {
  const a = clamp01(alpha);
  const b = clamp01(beta);
  return {
    model: (1 - b) * (1 - a),
    market: (1 - b) * a,
    longshot: b,
  };
}

export function formatBlendReadout(alpha, beta) {
  const w = blendWeights(alpha, beta);
  const pct = (x) => `${Math.round(x * 1000) / 10}%`;

  if (w.longshot >= 0.999) {
    return "Displayed score = 100% longshots (market blend not used at 100% upside)";
  }
  if (w.market < 0.001 && w.longshot < 0.001) {
    return "Displayed score = 100% core models";
  }
  if (w.longshot < 0.001) {
    if (w.market < 0.001) return "Displayed score = 100% core models";
    if (w.model < 0.001) return "Displayed score = 100% live odds";
    return `Displayed score = ${pct(w.model)} models + ${pct(w.market)} live odds`;
  }
  const mid = w.market + w.model;
  if (mid < 0.001) {
    return `Displayed score = ${pct(w.longshot)} longshots`;
  }
  return `Displayed score = ${pct(mid)} (${pct(w.model)} models + ${pct(w.market)} odds) + ${pct(w.longshot)} longshots`;
}

export function enrichHorses(horses, oddsLookup, marketAlpha, upsideBeta, normalizeHorseName) {
  const alpha = clamp01(marketAlpha);
  const beta = clamp01(upsideBeta);
  return (horses ?? []).map((h) => {
    const key = normalizeHorseName(h.horse_name);
    const o = oddsLookup?.get(key);
    const ms = o?.market_strength;
    const cs = h.composite_score ?? 0;
    const li = h.longshot_index ?? 0;
    const hasMs = ms != null && Number.isFinite(Number(ms));
    const compositeWithMarket = hasMs ? (1 - alpha) * cs + alpha * Number(ms) : cs;
    const compositeWithUpside =
      (1 - beta) * compositeWithMarket + beta * (Number(li) || 0);
    const msLive = hasMs ? Number(ms) : null;
    const upsideGap =
      msLive != null && h.longshot_index != null
        ? Number(h.longshot_index) - msLive
        : null;
    return {
      ...h,
      live_odds_str: o?.odds_str ?? null,
      live_implied_probability: o?.implied_probability ?? null,
      market_strength_live: msLive,
      composite_with_market: compositeWithMarket,
      composite_with_upside: compositeWithUpside,
      upside_gap: upsideGap,
    };
  });
}

export const CORE_STRATEGY_TARGETS = ["target_FP", "target_top3", "target_top5"];
export const LONGSHOT_STRATEGY_TARGETS = [
  "target_ml_rank_minus_finish",
  "target_top5_ml_rank_gt4",
  "target_deep_closer_top5",
];

export function strategyLabel(target) {
  const labels = {
    target_FP: "Finish position",
    target_top3: "Top 3",
    target_top5: "Top 5",
    target_ml_rank_minus_finish: "ML beat (rank − finish)",
    target_top5_ml_rank_gt4: "Longshot top 5 (ML > 4)",
    target_deep_closer_top5: "Longshot top 5 (ML ≥ 4)",
  };
  return labels[target] ?? target;
}
