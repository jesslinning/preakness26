/**
 * Browser port of app/scenarios.py _scenario_k / softmax chain for "composite" preset.
 * Scores come from enriched horses' composite_with_market (model + optional live pool blend).
 */

const MASK = -1e18;

/** Matches app/cli.py argparse defaults for scenario caps. */
export const EXOTIC_CLI_DEFAULTS = {
  exacta: { k: 2, maxTickets: 56 },
  trifecta: { k: 3, maxTickets: 120 },
  superfecta: { k: 4, maxTickets: 200 },
};

function softmax(logits) {
  const mx = Math.max(...logits);
  const z = logits.map((x) => x - mx);
  const e = z.map((x) => Math.exp(Math.min(80, Math.max(-80, x))));
  const s = e.reduce((a, b) => a + b, 0);
  return e.map((x) => x / s);
}

function probsRemaining(scores, excludeIndices) {
  const s = scores.slice();
  const ex = new Set(excludeIndices);
  for (let i = 0; i < s.length; i++) {
    if (ex.has(i)) s[i] = MASK;
  }
  return softmax(s);
}

function orderedFinishNaiveProb(scores, horseIndices) {
  let naive = 1;
  const exclude = new Set();
  for (const idx of horseIndices) {
    const p = probsRemaining(scores, exclude);
    naive *= p[idx];
    exclude.add(idx);
  }
  return naive;
}

/** itertools.permutations(pool, k): order matches Python for same pool array order. */
function permutations(pool, k) {
  if (k === 0) return [[]];
  if (pool.length < k) return [];
  const out = [];
  for (let i = 0; i < pool.length; i++) {
    const head = pool[i];
    const rest = [...pool.slice(0, i), ...pool.slice(i + 1)];
    for (const tail of permutations(rest, k - 1)) {
      out.push([head, ...tail]);
    }
  }
  return out;
}

const KEYS_BY_K = {
  2: ["first", "second"],
  3: ["first", "second", "third"],
  4: ["first", "second", "third", "fourth"],
};

/**
 * @param {Array<{ horse_name: string, composite_with_market?: number }>} horsesEnriched
 * @param {object} opts
 * @param {number} opts.k
 * @param {string} opts.betType
 * @param {number} opts.topN
 * @param {number} opts.maxTickets
 * @param {number} opts.costPerTicket
 * @param {string} [opts.preset]
 * @param {number|null} [opts.payoutIfWin]
 */
export function scenarioKFromHorses(horsesEnriched, opts) {
  const {
    k,
    betType,
    topN,
    maxTickets,
    costPerTicket,
    preset = "composite",
    payoutIfWin = null,
  } = opts;

  const keys = KEYS_BY_K[k];
  if (!keys) throw new Error(`scenarioKFromHorses: unsupported k=${k}`);

  const names = horsesEnriched.map((h) => h.horse_name);
  const scores = horsesEnriched.map((h) => {
    const v = h.composite_with_market;
    if (v == null || !Number.isFinite(Number(v))) return 0;
    return Number(v);
  });

  const idxMap = new Map(names.map((n, i) => [n, i]));

  const indexed = names.map((name, i) => ({ name, score: scores[i] }));
  indexed.sort((a, b) => b.score - a.score);
  const horsesSubset = indexed.slice(0, topN).map((x) => x.name);

  const tickets = [];
  for (const perm of permutations(horsesSubset, k)) {
    const idxs = perm.map((h) => idxMap.get(h));
    const naive = orderedFinishNaiveProb(scores, idxs);
    /** @type {Record<string, unknown>} */
    const row = {
      naive_probability: naive,
      note: "illustrative chained softmax — not calibrated track probability",
    };
    perm.forEach((name, m) => {
      row[keys[m]] = name;
    });
    if (payoutIfWin != null) {
      row.expected_value_per_dollar_stake = naive * payoutIfWin - costPerTicket;
    }
    tickets.push(row);
  }

  tickets.sort((a, b) => b.naive_probability - a.naive_probability);
  const capped = maxTickets > 0 ? tickets.slice(0, maxTickets) : tickets;
  const ticketCount = capped.length;

  return {
    bet_type: betType,
    preset,
    top_n: topN,
    cost_per_ticket: costPerTicket,
    ticket_count: ticketCount,
    total_cost: ticketCount * costPerTicket,
    tickets: capped,
  };
}

/**
 * @param {Array<{ horse_name: string, composite_with_market?: number }>} horsesEnriched
 * @param {"exacta"|"trifecta"|"superfecta"} kind
 * @param {object|null} staticPayload — scenarios.json fragment (top_n, cost_per_ticket, preset, bet_type)
 */
export function exoticScenarioFromJsonMeta(horsesEnriched, kind, staticPayload) {
  const defaults = EXOTIC_CLI_DEFAULTS[kind];
  if (!defaults) return null;
  const sp = staticPayload ?? {};
  const topN = typeof sp.top_n === "number" ? sp.top_n : kind === "exacta" ? 8 : 10;
  const costPerTicket =
    typeof sp.cost_per_ticket === "number" ? sp.cost_per_ticket : kind === "exacta" ? 1.0 : kind === "trifecta" ? 0.5 : 0.1;

  return scenarioKFromHorses(horsesEnriched, {
    k: defaults.k,
    betType: sp.bet_type ?? kind,
    topN,
    maxTickets: defaults.maxTickets,
    costPerTicket,
    preset: sp.preset ?? "composite",
    payoutIfWin: null,
  });
}
