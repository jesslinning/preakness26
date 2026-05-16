/**
 * In-app glossary — casual explanations for race fans (no raw data file jargon).
 * Section ids keep prefix `def-` for deep links from column headers.
 */
function fmtWeight(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toFixed(2);
}

export function DefinitionsTab({ blendWeights, longshotBlendWeights }) {
  const w = blendWeights ?? {};
  const lw = longshotBlendWeights ?? {};

  return (
    <div className="definitions">
      <section className="card def-card" id="def-modeling-overview">
        <h2>Blended modeling strategies</h2>
        <p>
          Predictions combine <strong>six DataRobot average blends</strong>: three core strategies
          (finish position, top 3, top 5) and three longshot strategies. Rankings apply them in
          nested steps—core composite first, then optional live odds (
          <a href="#def-market-blend">α</a>), then longshot models (
          <a href="#def-upside-blend">β</a>). Each slider step replaces part of the previous
          result, not added on top.
        </p>
      </section>

      <section className="card def-card" id="def-blend-weights">
        <h2>Blend weights</h2>
        <p>
          Fixed weights from the prediction bundle (from your current data file):
        </p>
        <h3 className="def-subhead">Core composite</h3>
        <dl className="glossary glossary--weights">
          <dt>Top 3 (ensemble_top3)</dt>
          <dd>{fmtWeight(w.ensemble_top3)}</dd>
          <dt>Top 5 (ensemble_top5)</dt>
          <dd>{fmtWeight(w.ensemble_top5)}</dd>
          <dt>Finish position (fp_strength)</dt>
          <dd>{fmtWeight(w.fp_strength)}</dd>
        </dl>
        <h3 className="def-subhead">Longshot index</h3>
        <dl className="glossary glossary--weights">
          <dt>ML beat (ml_beat_strength)</dt>
          <dd>{fmtWeight(lw.ml_beat_strength)}</dd>
          <dt>Top 5 strict (longshot_top5_strict)</dt>
          <dd>{fmtWeight(lw.longshot_top5_strict)}</dd>
          <dt>Top 5 broad (longshot_top5_broad)</dt>
          <dd>{fmtWeight(lw.longshot_top5_broad)}</dd>
        </dl>
        <p className="muted fine-print">
          See the <strong>Models</strong> tab for each strategy’s five child models in the blender.
        </p>
      </section>

      <section className="card def-card" id="def-horse">
        <h2>Horse</h2>
        <p>
          The name of the runner. Everything on this page lines up by horse so you are always
          comparing the same animal across different predictions.
        </p>
      </section>

      <section className="card def-card" id="def-composite-score">
        <h2>Composite score</h2>
        <p>
          One <strong>overall rating per horse</strong> so you can sort the whole field on a
          single scale. Under the hood it mixes three ideas: how likely the horse is to finish
          in the Top 3, how likely in the Top 5, and how strongly the finish-position models
          like the horse. This is a <em>rough</em> ranking tool—not a precise “chance to win
          the Preakness” number.
        </p>
        <p>
          Those three pieces are blended using fixed <strong>weights</strong> (by default: half
          from Top 3, forty percent from Top 5, ten percent from finish-position strength). The
          classifiers already speak in chances between 0 and 100%; finish predictions are
          converted to <strong>FP strength</strong> (below) so “expected place” does not drown
          out everything else.
        </p>
        <p>
          This is the <strong>core model score</strong> before live odds or longshot blends.
          Rankings and Exotics use the nested <strong>blended score</strong> after α and β
          (see <a href="#def-composite-with-upside">Blended score</a>).
        </p>
        <p>
          If those weights were changed, the order of horses would change too—you would still
          see the same building blocks in the table so nothing is hidden.
        </p>
      </section>

      <section className="card def-card" id="def-ensemble-top3">
        <h2>Ensemble top-3</h2>
        <p>
          The <strong>average likelihood across models</strong> that each predict whether this
          horse will finish in the <strong>Top 3</strong>. Several separate models each output a
          probability for that yes/no question; this column is simply their average—think of it
          as the crowd opinion among those models for a top-three finish.
        </p>
      </section>

      <section className="card def-card" id="def-ensemble-top5">
        <h2>Ensemble top-5</h2>
        <p>
          The same idea as ensemble Top 3, but for finishing in the <strong>Top 5</strong>:
          several models each estimate that chance, and this column averages them. Asking “top
          five?” is easier than “top three?”, so this number is often a bit kinder to longer
          shots than Top 3 alone.
        </p>
      </section>

      <section className="card def-card" id="def-fp-strength">
        <h2>FP strength</h2>
        <p>
          A score from <strong>weak to strong</strong> summarizing what the finish-position models
          expect: each model guesses an expected finishing place (lower place is better). We
          average those guesses, then rank every horse in the field so the best-looking picks
          sit near the top and the weaker ones near the bottom. That keeps finish predictions on
          a similar kind of scale as the Top 3 / Top 5 chances before they are mixed in—with
          only a <strong>small share of the blend</strong> so shaky place estimates do not
          steamroll the rest.
        </p>
      </section>

      <section className="card def-card" id="def-mean-fp-pred">
        <h2>Mean FP pred.</h2>
        <p>
          The <strong>average predicted finishing position</strong> from all the
          finish-position models (each one outputs something like an “expected place” number;
          lower means a better expected finish). This is the raw average before it is turned
          into FP strength—handy for seeing whether those models agree or argue about a horse.
        </p>
      </section>

      <section className="card def-card" id="def-composite-with-upside">
        <h2>Blended score (displayed)</h2>
        <p>
          The number you sort on in <strong>Rankings</strong> after both header sliders. It is built
          in two nested steps—not three parallel weights:
        </p>
        <ol className="def-list">
          <li>
            <strong>Core composite</strong> (Top 3 / Top 5 / FP blend from this card).
          </li>
          <li>
            <strong>Market step (α):</strong>{" "}
            <strong>composite_with_market = (1 − α) × core + α × market strength</strong> when live
            odds match the horse.
          </li>
          <li>
            <strong>Upside step (β):</strong>{" "}
            <strong>blended = (1 − β) × composite_with_market + β × longshot_index</strong>.
          </li>
        </ol>
        <p>
          At <strong>β = 100%</strong>, rankings use longshot models only and α is ignored. Exacta,
          trifecta, and superfecta naive probabilities use this same blended score.
        </p>
      </section>

      <section className="card def-card" id="def-longshot-index">
        <h2>Longshot index</h2>
        <p>
          A single 0–1 score per horse from three longshot blend strategies: how much the horse
          beats its morning-line rank, strict longshot top-5 probability, and a broader longshot
          top-5 signal. Weights default to 50% / 30% / 20% (see{" "}
          <a href="#def-blend-weights">Blend weights</a>).
        </p>
        <p>
          The <strong>Longshots</strong> tab sorts by this index. The <strong>Upside blend (β)</strong>{" "}
          slider folds it into the main Rankings blended score.
        </p>
      </section>

      <section className="card def-card" id="def-upside-blend">
        <h2>Upside blend (β)</h2>
        <p>
          Step 2 after market blend: tilts the displayed score toward{" "}
          <a href="#def-longshot-index">longshot index</a>. Formula:{" "}
          <strong>(1 − β) × composite_with_market + β × longshot_index</strong>. At 0% you ignore
          longshots; at 100% you use longshots only and α does not apply.
        </p>
      </section>

      <section className="card def-card" id="def-upside-gap">
        <h2>Upside gap</h2>
        <p>
          <strong>Longshot index − live market strength</strong> when both exist. Positive means the
          longshot models like the horse more than the betting pool’s implied ranking—a possible
          value angle (not a guarantee).
        </p>
      </section>

      <section className="card def-card" id="def-market-blend">
        <h2>Market blend (α)</h2>
        <p>
          When the live odds source lists a horse by name, you can tilt the{" "}
          <strong>core composite</strong> toward what the pool is doing. The slider sets{" "}
          <strong>α</strong> (alpha): each horse’s intermediate score becomes{" "}
          <strong>(1 − α) × core composite + α × market strength</strong>.{" "}
          <strong>Market strength</strong> is a 0–1 rank among horses on that page (see{" "}
          <a href="#def-market-strength-live">Market strength (live)</a>). Then β may blend in
          longshots (see <a href="#def-upside-blend">Upside blend (β)</a>).
        </p>
        <p>
          If a runner <strong>does not</strong> appear on the live odds page, there is no market
          term for that horse—the composite stays <strong>model-only</strong> for them even while
          other horses get the mix. That is why favorites with pool money can move up in the table
          while a long shot missing from the widget stays on pure model scores.
        </p>
        <p>
          Use the header <strong>slider (0%–100%)</strong> or <strong>type a percent</strong> in
          the small box to set α: <strong>0%</strong> means no pool weight (model-only for horses
          that have market data; still model-only for names not on the widget), and{" "}
          <strong>100%</strong> means use only market strength where it exists. Values in between
          interpolate. Exacta, trifecta, and superfecta tables use the <strong>same</strong> blended
          composite, so changing the blend reshapes those “naive” ticket probabilities too when odds
          are loaded.
        </p>
      </section>

      <section className="card def-card" id="def-live-odds-col">
        <h2>Live odds</h2>
        <p>
          Pool-style <strong>fractional odds</strong> (for example 5/1) for the Preakness field,
          matched to each horse by name. The app refreshes them from Horse Racing Nation’s
          Preakness odds page:{" "}
          <a
            href="https://www.horseracingnation.com/news/Preakness_betting_odds_Great_White_among_favorites_early_123"
            target="_blank"
            rel="noopener noreferrer"
          >
            Preakness 2026: updated win odds from Laurel Park
          </a>
          . That page publishes a field table with current win odds (not a live tote feed).
        </p>
        <p>
          Sorting the <strong>Live odds</strong> column uses the{" "}
          <strong>implied win probability</strong> (for a/b odds, b ÷ (a + b)).
        </p>
      </section>

      <section className="card def-card" id="def-market-strength-live">
        <h2>Market strength (live)</h2>
        <p>
          A 0–1 score from <strong>where the horse sits in the live implied-probability
          ranking</strong> among entries on the live odds page—short-priced horses score higher.
          It is defined only when the source lists the horse.
        </p>
      </section>

      <section className="card def-card" id="def-softmax">
        <h2>Softmax</h2>
        <p>
          A way to turn a set of strength scores (one per horse) into a set of <strong>shares
          that add up to 100%</strong>. Horses with higher scores get a bigger share. It is a
          common way to go from “who looks better on paper” to a simple win-style split when you
          do not have a separate win model.
        </p>
        <p>
          The math behind it is a little technical, but the idea is: spread the field’s
          confidence across all entries in a single step, in proportion to how strong each
          horse’s score is.
        </p>
      </section>

      <section className="card def-card" id="def-softmax-chains">
        <h2>Softmax chains (“naive” exotic probabilities)</h2>
        <p>
          For win / place / show, a rough order is often enough. <strong>Exacta, trifecta, and
          superfecta</strong> care about <strong>order</strong> (1st, 2nd, 3rd, 4th). This app
          builds a <em>rough</em> storybook probability by repeating a simple pattern:
        </p>
        <ol className="def-list">
          <li>Pick 1st using a softmax over the <strong>whole</strong> field (scores = blended score,
            including α and β when set).</li>
          <li>Remove that horse, then pick 2nd from the <strong>remaining</strong> horses with
            the same style of split.</li>
          <li>Do the same for 3rd and 4th when you are looking at tris and supers.</li>
        </ol>
        <p>
          That chain produces a <strong>naive probability</strong> per ordered ticket; the Exotics
          UI turns those into <strong>Rel. Strength</strong> for easier comparison—not for matching
          the live betting pool or a full race simulation.
        </p>
      </section>

      <section className="card def-card" id="def-naive-p">
        <h2>Rel. Strength (naive-based)</h2>
        <p>
          The <strong>Exotics</strong> tables show <strong>Rel. Strength</strong>, not raw naive
          percentages. Each row’s strength is its share of the <strong>best row on the current
          list</strong> (top = 100%). Under the hood that ranking still comes from{" "}
          <strong>naive probability</strong>: the chained-softmax story on the{" "}
          <strong>Softmax chains</strong> card—same composite as Rankings, pick 1st from the field,
          then 2nd from who’s left, and so on, and multiply the steps for one exact finish order.
        </p>
        <p>
          In <strong>Straight</strong> view, Rel. Strength compares each ordered ticket to the
          strongest ordered ticket in the table. In <strong>Box</strong> view, horses are grouped as
          an unordered set; strength uses the <strong>sum</strong> of naive probabilities for every
          straight ticket in the list that matches that set, compared to the strongest such set on
          the list. The narrow bar is the same ratio as the percentage.
        </p>
        <p>
          Think of it as a <strong>storybook fair comparison</strong>: every ticket or set is judged
          with the same recipe so you can see which combinations look stronger or weaker next to each
          other. It is <strong>not</strong> the track’s parimutuel price, a tote payout, or what you
          would get from simulating every possible order in the race.
        </p>
      </section>

      <section className="card def-card def-card--compact">
        <h2>More terms (short glossary)</h2>
        <dl className="glossary">
          <dt>Rankings tab</dt>
          <dd>Full prediction table for the field: one composite score (model blend plus optional
            live market mix) and the building blocks. Tap a column header to sort by that number
            or by name.</dd>

          <dt>Top N (Exotics)</dt>
          <dd>Only ordered bets built from the strongest handful of horses (by that screen’s
            score) are listed, to keep the list manageable. Anyone outside that group is left
            out even if they could still hit.</dd>

          <dt>Multiple models</dt>
          <dd>Several automated predictions are averaged or blended for each horse—similar to
            asking a few handicappers and combining their opinions.</dd>

          <dt>Heuristic vs calibrated</dt>
          <dd><strong>Heuristic</strong>: built to be easy to explore and compare.{" "}
            <strong>Calibrated</strong>: tuned to match real-world hit rates over many races
            (not what this tool tries to do).</dd>
        </dl>
      </section>
    </div>
  );
}
