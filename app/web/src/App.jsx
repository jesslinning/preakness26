import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { DefinitionsTab } from "./Definitions.jsx";
import { GlossaryTerm } from "./GlossaryTerm.jsx";
import { HorseLink } from "./HorseLink.jsx";
import { exoticScenarioFromJsonMeta } from "./exoticScenarios.js";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "rankings", label: "Rankings" },
  { id: "exotics", label: "Exotics" },
  { id: "models", label: "Models" },
  { id: "definitions", label: "Definitions" },
];

const EXOTIC_KINDS = ["exacta", "trifecta", "superfecta"];

function pct(x) {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(2)}%`;
}

/** Adaptive precision so tiny chained probabilities are not all "0.00%". */
function formatNaiveP(p) {
  if (p == null || Number.isNaN(p)) return "—";
  if (p <= 0) return "0%";
  const pct100 = p * 100;
  if (pct100 >= 0.01) return `${pct100.toFixed(2)}%`;
  if (pct100 >= 0.0001) return `${pct100.toFixed(4)}%`;
  return `${pct100.toFixed(6)}%`;
}

/** Canonical key for an unordered set of horses (box-style grouping). */
function boxKeyFromTicket(ticket, cols) {
  const names = cols.map((c) => ticket[c]).filter((x) => x != null && x !== "");
  return [...names]
    .sort((a, b) =>
      String(a).localeCompare(String(b), undefined, { sensitivity: "base" })
    )
    .join("|");
}

/**
 * Sum naive probabilities for tickets sharing the same unordered horse set.
 * Only permutations present in `tickets` are included (respects list truncation).
 */
function aggregateBoxRows(tickets, cols) {
  const map = new Map();
  for (const t of tickets) {
    const key = boxKeyFromTicket(t, cols);
    const p = Number(t.naive_probability);
    const safeP = Number.isFinite(p) ? p : 0;
    const prev = map.get(key);
    if (prev) {
      prev.sum += safeP;
      prev.count += 1;
    } else {
      const horses = cols.map((c) => t[c]);
      map.set(key, {
        key,
        horsesSorted: [...horses].sort((a, b) =>
          String(a).localeCompare(String(b), undefined, { sensitivity: "base" })
        ),
        sum: safeP,
        count: 1,
      });
    }
  }
  return [...map.values()].sort((a, b) => b.sum - a.sum);
}

function fmtScore(x) {
  if (x == null || Number.isNaN(x)) return "—";
  return Number(x).toFixed(4);
}

const API_ROOT = "/api";

function liveOddsUnreachableMessage() {
  if (import.meta.env.DEV) {
    return "Live odds API is not reachable (nothing on port 8000). Run `npm run api` in a second terminal, or `npm run dev:all` to start the API and Vite together.";
  }
  return "Live odds need the Python API on the same host. In Railway, set the service Root Directory to the repository root (not app/web) and use the root railway.toml so FastAPI serves /api and the Vite build—see comment in /railway.toml.";
}

/** Match prediction CSV names to KYDerby.com widget names. */
function normalizeHorseName(s) {
  return String(s ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .toUpperCase();
}

function buildOddsLookup(apiHorses) {
  const m = new Map();
  for (const h of apiHorses ?? []) {
    const key = h.horse_name_normalized ?? normalizeHorseName(h.horse_name);
    m.set(key, h);
  }
  return m;
}

/** @param {string | null | undefined} iso */
function formatLiveOddsTimestamp(iso, tick) {
  void tick;
  if (!iso) return { primary: "Live odds not loaded yet.", detail: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { primary: "Live odds time unavailable.", detail: "" };
  const abs = d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
  const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
  let rel;
  if (sec < 45) rel = "just now";
  else if (sec < 3600) rel = `${Math.floor(sec / 60)}m ago`;
  else if (sec < 86400) rel = `${Math.floor(sec / 3600)}h ago`;
  else rel = `${Math.floor(sec / 86400)}d ago`;
  return {
    primary: `Live odds as of ${abs} (${rel}).`,
    detail: `UTC equivalent: ${iso}`,
  };
}

function enrichHorses(horses, oddsLookup, marketAlpha) {
  const a = Number(marketAlpha);
  const alpha = Number.isFinite(a) ? Math.min(1, Math.max(0, a)) : 0.1;
  return (horses ?? []).map((h) => {
    const o = oddsLookup?.get(normalizeHorseName(h.horse_name));
    const ms = o?.market_strength;
    const cs = h.composite_score ?? 0;
    const hasMs = ms != null && Number.isFinite(Number(ms));
    const compositeWithMarket = hasMs
      ? (1 - alpha) * cs + alpha * Number(ms)
      : cs;
    return {
      ...h,
      live_odds_str: o?.odds_str ?? null,
      live_implied_probability: o?.implied_probability ?? null,
      market_strength_live: hasMs ? Number(ms) : null,
      composite_with_market: compositeWithMarket,
    };
  });
}

/** Sortable prediction table header: label + sort control + glossary icon (icon-only). */
function PredictionSortHeader({ sortKey, label, predictionSort, onSort, glossary }) {
  const active = predictionSort.key === sortKey;
  const ariaSort = active
    ? predictionSort.dir === "asc"
      ? "ascending"
      : "descending"
    : undefined;

  const sortAriaLabel = active
    ? `Sorted by ${label}, ${predictionSort.dir === "asc" ? "ascending" : "descending"}. Press to reverse order.`
    : `Sort table by ${label}`;

  return (
    <th scope="col" aria-sort={ariaSort}>
      <div className="th-ranking">
        <button
          type="button"
          className="th-ranking__sort"
          aria-label={sortAriaLabel}
          onClick={() => onSort(sortKey)}
        >
          <span>{label}</span>
          <span
            className={
              active ? "th-ranking__chev th-ranking__chev--active" : "th-ranking__chev"
            }
            aria-hidden
          >
            {active ? (predictionSort.dir === "asc" ? "↑" : "↓") : "↕"}
          </span>
        </button>
        {glossary}
      </div>
    </th>
  );
}

export default function App() {
  const [combined, setCombined] = useState(null);
  const [scenarios, setScenarios] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("overview");
  const [definitionScrollTarget, setDefinitionScrollTarget] = useState(null);
  const [predictionSort, setPredictionSort] = useState({
    key: "composite_with_market",
    dir: "desc",
  });
  const [liveOdds, setLiveOdds] = useState(null);
  const [liveOddsBanner, setLiveOddsBanner] = useState(null);
  const [liveOddsRefreshing, setLiveOddsRefreshing] = useState(false);
  const [marketAlpha, setMarketAlpha] = useState(0.1);
  /** While focused, raw string in the percent number box (optional decimals). */
  const [blendPercentDraft, setBlendPercentDraft] = useState(null);
  const [clockTick, setClockTick] = useState(0);
  const [exoticKind, setExoticKind] = useState("exacta");

  const goToDefinition = useCallback((defId) => {
    setTab("definitions");
    setDefinitionScrollTarget(defId);
  }, []);

  useEffect(() => {
    if (tab !== "definitions" || !definitionScrollTarget) return;
    const id = definitionScrollTarget;
    const t = window.setTimeout(() => {
      document.getElementById(`def-${id}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      setDefinitionScrollTarget(null);
    }, 80);
    return () => window.clearTimeout(t);
  }, [tab, definitionScrollTarget]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [c, s] = await Promise.all([
          fetch(`${import.meta.env.BASE_URL}combined_predictions.json`).then((r) => {
            if (!r.ok) throw new Error(`combined_predictions.json: ${r.status}`);
            return r.json();
          }),
          fetch(`${import.meta.env.BASE_URL}scenarios.json`).then((r) => {
            if (!r.ok) throw new Error(`scenarios.json: ${r.status}`);
            return r.json();
          }),
        ]);
        if (!cancelled) {
          setCombined(c);
          setScenarios(s);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadLiveOdds = useCallback(async (method = "GET") => {
    try {
      const url =
        method === "POST"
          ? `${API_ROOT}/live-odds/refresh`
          : `${API_ROOT}/live-odds`;
      const r = await fetch(url, method === "POST" ? { method: "POST" } : {});

      if (!r.ok) {
        setLiveOddsBanner(liveOddsUnreachableMessage());
        if (method === "GET") {
          setLiveOdds(null);
        }
        return;
      }

      let data = {};
      try {
        data = await r.json();
      } catch {
        setLiveOddsBanner(liveOddsUnreachableMessage());
        if (method === "GET") {
          setLiveOdds(null);
        }
        return;
      }

      if (data?.horses === undefined) {
        setLiveOddsBanner(liveOddsUnreachableMessage());
        if (method === "GET") {
          setLiveOdds(null);
        }
        return;
      }

      setLiveOdds(data);
      setLiveOddsBanner(
        data?.error && (!data?.horses || data.horses.length === 0)
          ? String(data.error)
          : null
      );
    } catch (e) {
      setLiveOddsBanner(
        e?.message?.includes("Failed to fetch") || e?.name === "TypeError"
          ? liveOddsUnreachableMessage()
          : e?.message || liveOddsUnreachableMessage()
      );
      if (method === "GET") {
        setLiveOdds(null);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadLiveOdds("GET");
    })();
    const id = window.setInterval(() => {
      if (!cancelled) loadLiveOdds("GET");
    }, 90_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [loadLiveOdds]);

  useEffect(() => {
    const id = window.setInterval(() => setClockTick((t) => t + 1), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const refreshLiveOddsManual = useCallback(async () => {
    setLiveOddsRefreshing(true);
    try {
      await loadLiveOdds("POST");
    } finally {
      setLiveOddsRefreshing(false);
    }
  }, [loadLiveOdds]);

  const commitBlendPercentDraft = useCallback(() => {
    if (blendPercentDraft === null) return;
    const t = blendPercentDraft.trim().replace(/%$/u, "");
    if (t === "") {
      setBlendPercentDraft(null);
      return;
    }
    const n = parseFloat(t);
    if (!Number.isFinite(n)) {
      setBlendPercentDraft(null);
      return;
    }
    const clamped = Math.min(100, Math.max(0, n));
    setMarketAlpha(Math.round(clamped * 10) / 1000);
    setBlendPercentDraft(null);
  }, [blendPercentDraft]);

  const oddsLookup = useMemo(
    () => buildOddsLookup(liveOdds?.horses),
    [liveOdds?.horses]
  );

  const horsesEnriched = useMemo(
    () => enrichHorses(combined?.horses, oddsLookup, marketAlpha),
    [combined?.horses, oddsLookup, marketAlpha]
  );

  const horsesSorted = useMemo(() => {
    if (!horsesEnriched.length) return [];
    return [...horsesEnriched].sort(
      (a, b) => (b.composite_with_market ?? 0) - (a.composite_with_market ?? 0)
    );
  }, [horsesEnriched]);

  const ts = formatLiveOddsTimestamp(liveOdds?.fetched_at, clockTick);

  const togglePredictionSort = useCallback((key) => {
    setPredictionSort((prev) => {
      if (prev.key === key) {
        return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      return {
        key,
        dir: key === "horse_name" ? "asc" : "desc",
      };
    });
  }, []);

  const predictionRows = useMemo(() => {
    const rows = [...horsesEnriched];
    const { key, dir } = predictionSort;
    const mul = dir === "asc" ? 1 : -1;

    const num = (v) => {
      if (v == null || v === "") return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };

    rows.sort((a, b) => {
      if (key === "horse_name") {
        const cmp = String(a.horse_name ?? "").localeCompare(
          String(b.horse_name ?? ""),
          undefined,
          { sensitivity: "base" }
        );
        return mul * cmp;
      }
      const na = num(a[key]);
      const nb = num(b[key]);
      if (na === null && nb === null) return 0;
      if (na === null) return 1;
      if (nb === null) return -1;
      return mul * (na - nb);
    });
    return rows;
  }, [horsesEnriched, predictionSort]);

  const maxComposite = useMemo(() => {
    if (!horsesSorted.length) return 1;
    const scores = horsesSorted.map((h) => h.composite_with_market ?? 0);
    return Math.max(...scores, 1e-9);
  }, [horsesSorted]);

  const exactaLive = useMemo(
    () =>
      horsesEnriched.length && scenarios?.exacta
        ? exoticScenarioFromJsonMeta(horsesEnriched, "exacta", scenarios.exacta)
        : null,
    [horsesEnriched, scenarios?.exacta]
  );
  const trifectaLive = useMemo(
    () =>
      horsesEnriched.length && scenarios?.trifecta
        ? exoticScenarioFromJsonMeta(horsesEnriched, "trifecta", scenarios.trifecta)
        : null,
    [horsesEnriched, scenarios?.trifecta]
  );
  const superfectaLive = useMemo(
    () =>
      horsesEnriched.length && scenarios?.superfecta
        ? exoticScenarioFromJsonMeta(horsesEnriched, "superfecta", scenarios.superfecta)
        : null,
    [horsesEnriched, scenarios?.superfecta]
  );

  const exoticDataLive = useMemo(() => {
    if (exoticKind === "exacta") return exactaLive;
    if (exoticKind === "trifecta") return trifectaLive;
    return superfectaLive;
  }, [exoticKind, exactaLive, trifectaLive, superfectaLive]);

  if (error) {
    return (
      <div className="shell">
        <header className="hero">
          <h1>Kentucky Derby prediction explorer</h1>
        </header>
        <div className="card error">
          <strong>Could not load JSON.</strong> Run{" "}
          <code className="mono">npm run data</code> from <code className="mono">app/web</code>{" "}
          (or copy <code className="mono">app/output/*.json</code> into{" "}
          <code className="mono">app/web/public/</code>), then refresh.
          <pre className="mono detail">{error}</pre>
        </div>
      </div>
    );
  }

  if (!combined || !scenarios) {
    return (
      <div className="shell">
        <p className="loading">Loading predictions…</p>
      </div>
    );
  }

  const w = scenarios.blend_weights ?? combined.blend_weights ?? {};
  const blendPercentTenth = Math.round(marketAlpha * 1000) / 10;

  return (
    <div className="shell">
      <header className="hero">
        <p className="eyebrow">Derby 2026 · ensemble view</p>
        <h1>Kentucky Derby prediction explorer</h1>
        <p className="lede">
          Heuristic blend of top-3 / top-5 classifiers and finish-position models. Exotic
          “naive” joints are illustrative softmax chains—not track prices.
        </p>
        <div className="weights">
          <span className="pill">
            top3 weight <strong>{w.ensemble_top3 ?? "—"}</strong>
          </span>
          <span className="pill">
            top5 weight <strong>{w.ensemble_top5 ?? "—"}</strong>
          </span>
          <span className="pill">
            FP strength weight <strong>{w.fp_strength ?? "—"}</strong>
          </span>
        </div>
        <div className="live-odds-bar">
          <p className="live-odds-bar__status" title={ts.detail}>
            {ts.primary}
          </p>
          {liveOddsBanner ? (
            <p className="live-odds-bar__warn" role="status">
              {liveOddsBanner}
            </p>
          ) : null}
          <div className="live-odds-bar__controls">
            <label className="live-odds-bar__slider">
              <span className="live-odds-bar__slider-label">
                <GlossaryTerm
                  name="Market blend"
                  defId="market-blend"
                  summary="Pool weight 0–100% mixed into the model composite when live odds match a horse (slider or type a percent)."
                  onNavigate={goToDefinition}
                >
                  Market blend (α)
                </GlossaryTerm>{" "}
                <span className="live-odds-bar__percent-inline" aria-live="polite">
                  <span className="live-odds-bar__percent-field">
                    <label htmlFor="market-blend-percent" className="sr-only">
                      Market blend percent (0 to 100)
                    </label>
                    <input
                      id="market-blend-percent"
                      type="text"
                      inputMode="decimal"
                      className="mono live-odds-bar__percent-input"
                      autoComplete="off"
                      spellCheck={false}
                      aria-label="Market blend percent, type 0 to 100"
                      value={
                        blendPercentDraft !== null
                          ? blendPercentDraft
                          : String(blendPercentTenth)
                      }
                      onChange={(e) => setBlendPercentDraft(e.target.value)}
                      onFocus={() => setBlendPercentDraft(String(blendPercentTenth))}
                      onBlur={commitBlendPercentDraft}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitBlendPercentDraft();
                          e.currentTarget.blur();
                        }
                      }}
                    />
                    <span className="live-odds-bar__percent-suffix" aria-hidden>
                      %
                    </span>
                  </span>
                </span>
              </span>
              <input
                type="range"
                min={0}
                max={100}
                step={0.1}
                value={blendPercentTenth}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setMarketAlpha(Math.round(v * 10) / 1000);
                }}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={blendPercentTenth}
                aria-label="Market blend percent slider"
              />
            </label>
            <button
              type="button"
              className="live-odds-bar__refresh"
              onClick={refreshLiveOddsManual}
              disabled={liveOddsRefreshing}
            >
              {liveOddsRefreshing ? "Refreshing…" : "Refresh odds"}
            </button>
          </div>
        </div>
        <p className="glossary-mobile-hint" role="note">
          <strong>Definitions:</strong> tap the circular{" "}
          <span className="glossary-mobile-hint__badge" aria-hidden>
            <svg viewBox="0 0 24 24" focusable="false">
              <path
                fill="currentColor"
                d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"
              />
            </svg>
          </span>{" "}
          button beside a term for a one-line summary and <em>Open in Definitions</em>.
        </p>
      </header>

      <div className="tabs-nav">
        <div className="tabs-nav__mobile">
          <label className="tabs-nav__label" htmlFor="section-nav">
            Jump to section
          </label>
          <select
            id="section-nav"
            className="tabs-nav__select"
            value={tab}
            onChange={(e) => setTab(e.target.value)}
          >
            {TABS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="tabs-scroll">
          <nav className="tabs" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={tab === t.id ? "tab active" : "tab"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {tab === "overview" && (
        <section className="card">
          <h2 className="h2-with-glossary">
            <GlossaryTerm
              name="Composite"
              defId="composite-score"
              summary="Model blend plus optional live market strength when odds match (same scale as exotic softmax scenarios)."
              onNavigate={goToDefinition}
            >
              Composite score
            </GlossaryTerm>{" "}
            <span className="h2-suffix">(top field)</span>
          </h2>
          <p className="muted">
            Composite blends model rankings with optional live pool strength when odds match;
            bar scale matches Rankings (max in field = 100%). Adjust the blend percentage (α)
            above when live odds are loaded.
          </p>
          <ul className="barlist">
            {horsesSorted.slice(0, 16).map((h) => {
              const barScore = h.composite_with_market ?? 0;
              return (
                <li key={h.horse_name}>
                  <span className="bar-name-wrap">
                    <HorseLink name={h.horse_name} className="bar-name" />
                    {h.live_odds_str ? (
                      <span className="bar-odds mono">{h.live_odds_str}</span>
                    ) : null}
                  </span>
                  <div className="bar-track">
                    <div
                      className="bar-fill"
                      style={{
                        width: `${(barScore / maxComposite) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="bar-val mono">{fmtScore(barScore)}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {tab === "rankings" && (
        <section className="card">
          <h2>Prediction ranking</h2>
          <p className="muted table-sort-hint">
            Tap a column heading to sort. The info icon opens the definition.
          </p>
          <p className="table-scroll-hint">Swipe sideways on small screens to see every column.</p>
          <div className="table-wrap">
            <table className="data dense data--sortable">
              <thead>
                <tr>
                  <PredictionSortHeader
                    sortKey="horse_name"
                    label="Horse"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Horse"
                        defId="horse"
                        summary="The runner name used to merge every model’s predictions onto one row per horse."
                        onNavigate={goToDefinition}
                      >
                        Horse
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="composite_with_market"
                    label="Composite"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Composite"
                        defId="composite-score"
                        summary="Model blend plus optional live market strength when odds match (same scale as exotic softmax scenarios)."
                        onNavigate={goToDefinition}
                      >
                        Composite
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="live_implied_probability"
                    label="Live odds"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Live odds"
                        defId="live-odds-col"
                        summary="Fractional pool-style odds from the official live odds page (matched by horse name). Sort uses implied win probability."
                        onNavigate={goToDefinition}
                      >
                        Live odds
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="market_strength_live"
                    label="Mkt str."
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Market strength"
                        defId="market-strength-live"
                        summary="0–1 rank from live implied probability among entries on the odds page—favorites score higher."
                        onNavigate={goToDefinition}
                      >
                        Mkt str.
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_top3"
                    label="Ensemble top3"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Ensemble top3"
                        defId="ensemble-top3"
                        summary="The average likelihood across models predicting if a horse will finish in the Top 3."
                        onNavigate={goToDefinition}
                      >
                        Ensemble top3
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_top5"
                    label="Ensemble top5"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Ensemble top5"
                        defId="ensemble-top5"
                        summary="The average likelihood across models predicting if a horse will finish in the Top 5."
                        onNavigate={goToDefinition}
                      >
                        Ensemble top5
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="fp_strength"
                    label="FP strength"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="FP strength"
                        defId="fp-strength"
                        summary="How strongly finish-position models favor this horse vs the field, scaled 0–1 from mean predicted place—it is down-weighted in the composite."
                        onNavigate={goToDefinition}
                      >
                        FP strength
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_fp_mean"
                    label="Mean FP pred."
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Mean FP pred."
                        defId="mean-fp-pred"
                        summary="The average predicted finishing position across FP models (each outputs expected place; lower means a better expected finish)."
                        onNavigate={goToDefinition}
                      >
                        Mean FP pred.
                      </GlossaryTerm>
                    }
                  />
                </tr>
              </thead>
              <tbody>
                {predictionRows.map((h) => (
                  <tr key={h.horse_name}>
                    <td>
                      <HorseLink name={h.horse_name} />
                    </td>
                    <td className="mono">{fmtScore(h.composite_with_market)}</td>
                    <td className="mono">
                      {h.live_odds_str ?? "—"}
                    </td>
                    <td className="mono">{fmtScore(h.market_strength_live)}</td>
                    <td className="mono">{fmtScore(h.ensemble_top3)}</td>
                    <td className="mono">{fmtScore(h.ensemble_top5)}</td>
                    <td className="mono">{fmtScore(h.fp_strength)}</td>
                    <td className="mono">{fmtScore(h.ensemble_fp_mean)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "exotics" && (
        <section className="card exotic-card">
          <div
            className="exotic-segments"
            role="tablist"
            aria-label="Exotic bet type"
          >
            {EXOTIC_KINDS.map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={exoticKind === k}
                className={
                  exoticKind === k
                    ? "exotic-segment exotic-segment--active"
                    : "exotic-segment"
                }
                onClick={() => setExoticKind(k)}
              >
                {k.charAt(0).toUpperCase() + k.slice(1)}
              </button>
            ))}
          </div>
          <ExoticSection
            key={exoticKind}
            data={exoticDataLive}
            onNavigateDefinition={goToDefinition}
            embedded
          />
        </section>
      )}

      {tab === "definitions" && <DefinitionsTab />}

      {tab === "models" && (
        <section className="card">
          <h2>Source models ({combined.meta?.length ?? 0})</h2>
          <div className="table-wrap">
            <table className="data dense">
              <thead>
                <tr>
                  <th>Target</th>
                  <th>Model</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {(combined.meta ?? []).map((m) => (
                  <tr key={m.column_name}>
                    <td>
                      <span className={`tag tag-${m.target.replace("target_", "")}`}>
                        {m.target}
                      </span>
                    </td>
                    <td className="break">{m.model_label}</td>
                    <td className="mono muted">{m.model_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function ExoticSection({ data, onNavigateDefinition, embedded }) {
  const [displayMode, setDisplayMode] = useState("box");

  const cols = useMemo(() => {
    if (!data?.bet_type) return [];
    if (data.bet_type === "exacta") return ["first", "second"];
    if (data.bet_type === "trifecta") return ["first", "second", "third"];
    return ["first", "second", "third", "fourth"];
  }, [data?.bet_type]);

  const boxRows = useMemo(() => {
    if (!data?.tickets?.length || cols.length === 0) return [];
    return aggregateBoxRows(data.tickets, cols);
  }, [data?.tickets, cols]);

  const empty = <p className="muted">No scenario data.</p>;
  if (!data?.tickets?.length) {
    return embedded ? empty : <section className="card">{empty}</section>;
  }

  const maxStraight = data.tickets[0]?.naive_probability ?? 0;
  const maxBox = boxRows[0]?.sum ?? 0;

  const inner = (
    <>
      <h2 className="exotic-section__title">{data.bet_type}</h2>
      <p className="muted">
        Preset: <code className="mono">{data.preset}</code> · Top{" "}
        <strong>{data.top_n}</strong> horses considered · Showing{" "}
        <strong>{data.ticket_count}</strong> tickets · Cost per ticket: $
        {Number(data.cost_per_ticket).toFixed(2)} · Total{" "}
        <strong>${data.total_cost?.toFixed?.(2) ?? data.total_cost}</strong>
      </p>
      <p className="fine-print">{data.tickets[0]?.note}</p>

      <div
        className="exotic-view-toggle"
        role="group"
        aria-label="Ticket display mode"
      >
        <span className="exotic-view-toggle__label">View</span>
        <button
          type="button"
          className={
            displayMode === "box"
              ? "exotic-view-btn exotic-view-btn--active"
              : "exotic-view-btn"
          }
          aria-pressed={displayMode === "box"}
          onClick={() => setDisplayMode("box")}
        >
          Box
        </button>
        <button
          type="button"
          className={
            displayMode === "straight"
              ? "exotic-view-btn exotic-view-btn--active"
              : "exotic-view-btn"
          }
          aria-pressed={displayMode === "straight"}
          onClick={() => setDisplayMode("straight")}
        >
          Straight
        </button>
      </div>

      {displayMode === "box" ? (
        <p className="fine-print exotic-view-hint">
          Horses grouped by set (any finish order). Naive P is the{" "}
          <strong>sum</strong> of each listed straight ticket that uses that set—only permutations
          that appear in this table are included.
        </p>
      ) : null}

      <div className="table-wrap">
        {displayMode === "box" ? (
          <table className="data dense">
            <thead>
              <tr>
                <th scope="col">Horses</th>
                <th scope="col">
                  <div className="th-ranking th-ranking--exotic">
                    <span>Naive P (combined)</span>
                    <GlossaryTerm
                      variant="icon-only"
                      name="Combined naive probability"
                      defId="naive-p"
                      summary="Sum of naive probabilities for each straight ticket in this list that matches the same horse set (unordered)."
                      onNavigate={onNavigateDefinition}
                    >
                      Naive P (combined)
                    </GlossaryTerm>
                  </div>
                </th>
                <th scope="col" title="Finish orders from this table that belong to this set">
                  Orders
                </th>
                <th scope="col">
                  <div className="th-ranking th-ranking--exotic">
                    <span>Rel.</span>
                    <GlossaryTerm
                      variant="icon-only"
                      name="Relative naive strength"
                      defId="naive-p"
                      summary="Share of the strongest combined naive probability on this box list (top = 100%)."
                      onNavigate={onNavigateDefinition}
                    >
                      Rel.
                    </GlossaryTerm>
                  </div>
                </th>
                <th
                  scope="col"
                  className="exotic-bar-col"
                  aria-label="Relative strength bar"
                >
                  <span className="sr-only">Strength</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {boxRows.map((row) => {
                const rel = maxBox > 0 ? row.sum / maxBox : 0;
                const relPct = `${(rel * 100).toFixed(1)}%`;
                return (
                  <tr key={row.key}>
                    <td className="exotic-box-horses">
                      {row.horsesSorted.map((name, hi) => (
                        <span key={name} className="exotic-box-horse">
                          {hi > 0 ? (
                            <span className="exotic-box-sep" aria-hidden>
                              {" "}
                              ·{" "}
                            </span>
                          ) : null}
                          <HorseLink name={name} />
                        </span>
                      ))}
                    </td>
                    <td className="mono">{formatNaiveP(row.sum)}</td>
                    <td className="mono muted">{row.count}</td>
                    <td className="mono exotic-rel-pct">{relPct}</td>
                    <td className="exotic-bar-cell">
                      <div
                        className="exotic-rel-bar-track"
                        aria-hidden
                        title={`${relPct} of top box`}
                      >
                        <div
                          className="exotic-rel-bar-fill"
                          style={{ width: `${rel * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <table className="data dense">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
                <th scope="col">
                  <div className="th-ranking th-ranking--exotic">
                    <span>Naive P</span>
                    <GlossaryTerm
                      variant="icon-only"
                      name="Naive P"
                      defId="naive-p"
                      summary="Rough chained probability for this exact finishing order from the same composite as Rankings (optional market blend)—useful for comparing tickets, not for matching live pool odds."
                      onNavigate={onNavigateDefinition}
                    >
                      Naive P
                    </GlossaryTerm>
                  </div>
                </th>
                <th scope="col">
                  <div className="th-ranking th-ranking--exotic">
                    <span>Rel.</span>
                    <GlossaryTerm
                      variant="icon-only"
                      name="Relative naive strength"
                      defId="naive-p"
                      summary="Share of the strongest ticket’s naive probability on this list (top = 100%). Easier to scan than tiny absolute percentages."
                      onNavigate={onNavigateDefinition}
                    >
                      Rel.
                    </GlossaryTerm>
                  </div>
                </th>
                <th
                  scope="col"
                  className="exotic-bar-col"
                  aria-label="Relative strength bar"
                >
                  <span className="sr-only">Strength</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.tickets.map((t, i) => {
                const p = t.naive_probability;
                const rel =
                  maxStraight > 0 && p != null ? p / maxStraight : 0;
                const relPct = `${(rel * 100).toFixed(1)}%`;
                return (
                  <tr key={i}>
                    {cols.map((c) => (
                      <td key={c}>
                        <HorseLink name={t[c]} />
                      </td>
                    ))}
                    <td className="mono">{formatNaiveP(p)}</td>
                    <td className="mono exotic-rel-pct">{relPct}</td>
                    <td className="exotic-bar-cell">
                      <div
                        className="exotic-rel-bar-track"
                        aria-hidden
                        title={`${relPct} of top ticket`}
                      >
                        <div
                          className="exotic-rel-bar-fill"
                          style={{ width: `${rel * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );

  if (embedded) return inner;
  return <section className="card">{inner}</section>;
}
