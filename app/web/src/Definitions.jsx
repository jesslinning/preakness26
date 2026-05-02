/**
 * In-app glossary — casual explanations for race fans (no raw data file jargon).
 * Section ids keep prefix `def-` for deep links from column headers.
 */
export function DefinitionsTab() {
  return (
    <div className="definitions">
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
          the Derby” number.
        </p>
        <p>
          Those three pieces are blended using fixed <strong>weights</strong> (by default: half
          from Top 3, forty percent from Top 5, ten percent from finish-position strength). The
          classifiers already speak in chances between 0 and 100%; finish predictions are
          converted to <strong>FP strength</strong> (below) so “expected place” does not drown
          out everything else.
        </p>
        <p>
          When <strong>live pool odds</strong> are matched to a horse, the same column can
          further mix in <strong>market strength</strong> (see <a href="#def-market-blend">Market
          blend (α)</a>): <strong>(1 − α) ×</strong> that model blend <strong>+ α ×</strong> market
          strength. If no odds match, the score stays model-only. Exacta, trifecta, and superfecta
          naive probabilities use this same composite so they move with the slider when odds are
          loaded.
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

      <section className="card def-card" id="def-market-blend">
        <h2>Market blend (α)</h2>
        <p>
          When the live odds feed lists a horse by name, you can tilt the{" "}
          <a href="#def-composite-score">Composite score</a> toward what the betting pool is
          doing. The slider sets <strong>α</strong> (alpha): each horse’s composite becomes{" "}
          <strong>(1 − α) × model composite + α × market strength</strong>. Here{" "}
          <strong>model composite</strong> is the blended Top 3 / Top 5 / FP score from the CSV
          models alone; <strong>market strength</strong> is a 0–1 rank among horses that appear
          on the odds page (see <a href="#def-market-strength-live">Market strength (live)</a>).
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
          Pool-style <strong>fractional odds</strong> (for example 5/1) pulled from the
          Kentucky Derby live odds widget and matched by horse name. Sorting this column uses
          the <strong>implied win probability</strong> (for a/b odds, b ÷ (a + b)).
        </p>
      </section>

      <section className="card def-card" id="def-market-strength-live">
        <h2>Market strength (live)</h2>
        <p>
          A 0–1 score from <strong>where the horse sits in the live implied-probability
          ranking</strong> among entries on the odds page—short-priced horses score higher.
          It is defined only when that page lists the horse.
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
          <li>Pick 1st using a softmax over the <strong>whole</strong> field (scores = Composite,
            including optional market blend when live odds match).</li>
          <li>Remove that horse, then pick 2nd from the <strong>remaining</strong> horses with
            the same style of split.</li>
          <li>Do the same for 3rd and 4th when you are looking at tris and supers.</li>
        </ol>
        <p>
          The <strong>naive probability</strong> you see is the result of that chain. It is
          useful for <strong>comparing one ticket to another</strong> under the same rules—not
          for matching the live betting pool or a full race simulation.
        </p>
      </section>

      <section className="card def-card" id="def-naive-p">
        <h2>Naive P</h2>
        <p>
          Short for <strong>naive probability</strong>: the percentage shown on the{" "}
          <strong>Exotics</strong> tables for one <em>ordered</em> ticket. It comes from the softmax
          chain on the <strong>Softmax chains</strong> card above—using the same per-horse composite
          as the Rankings tab (including optional market blend when live odds are loaded)—pick 1st
          from the whole field, then 2nd from who is left, then 3rd and 4th the same way—and
          multiply those steps together to get one number for that exact finishing order.
        </p>
        <p>
          Raw naive probabilities are often <strong>tiny</strong>, so this app adds decimal places
          when needed so rows are not all “0.00%”. The <strong>Rel.</strong> column gives each ticket
          as a percentage of the <strong>strongest ticket on the current list</strong> (the top row is
          always 100%). The narrow bar is the same ratio—useful for spotting gaps between tickets
          without reading microscopic percentages.
        </p>
        <p>
          Use <strong>Box</strong> on Exotics to group horses as an unordered set and show{" "}
          <strong>combined</strong> naive probability (sum over straight tickets in the table that
          share those horses). Switch to <strong>Straight</strong> to see each exact finishing order
          and its own naive probability—the usual straight-ticket view.
        </p>
        <p>
          Think of it as a <strong>storybook fair comparison</strong>: every ticket is priced with
          the same recipe so you can see which combinations look stronger or weaker next to each
          other. It is <strong>not</strong> the track’s parimutuel price, a tote payout, or what
          you would get from simulating every possible order in the race.
        </p>
      </section>

      <section className="card def-card def-card--compact">
        <h2>More terms (short glossary)</h2>
        <dl className="glossary">
          <dt>Blend weights</dt>
          <dd>How much the overall score leans on Top 3 chance, Top 5 chance, and finish
            strength. If the three weights add up to 1, you can read the composite as a
            straight combination of those three ideas (each scaled so higher = better).</dd>

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
