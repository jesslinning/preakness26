#!/usr/bin/env python3
"""
CLI: merge batch prediction CSVs and emit combined CSV/JSON plus scenario JSON files.

Run from repo root::

    python -m app.cli

Or::

    python app/cli.py

Requires ``pandas`` and ``numpy``.

For a browser UI later: serve ``combined_predictions.json`` / ``scenarios.json`` statically,
or wrap ``build_bundle`` and ``scenarios`` in FastAPI and build a Vite/React client that
posts blend weights and scenario parameters.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.prediction_bundle import (
    build_bundle,
    bundle_to_json,
    default_output_dir,
    default_predictions_dir,
)
from app.scenarios import (
    exacta_scenario,
    ranking_table,
    superfecta_scenario,
    trifecta_scenario,
)

logger = logging.getLogger("app.cli")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Combine Preakness blend prediction CSVs and build scenarios.")
    p.add_argument(
        "--predictions-dir",
        type=Path,
        default=None,
        help=f"Directory with predictions_*.csv (default: {default_predictions_dir()})",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Write outputs here (default: {default_output_dir()})",
    )
    p.add_argument("--w-top3", type=float, default=0.5, dest="w_top3")
    p.add_argument("--w-top5", type=float, default=0.4, dest="w_top5")
    p.add_argument("--w-fp", type=float, default=0.1, dest="w_fp")
    p.add_argument("--exacta-top-n", type=int, default=8)
    p.add_argument("--trifecta-top-n", type=int, default=10)
    p.add_argument("--superfecta-top-n", type=int, default=10)
    p.add_argument("--exacta-max", type=int, default=56)
    p.add_argument("--trifecta-max", type=int, default=120)
    p.add_argument("--superfecta-max", type=int, default=200)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    pred_dir = args.predictions_dir or default_predictions_dir()
    out_dir = args.output_dir or default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    blend = {
        "ensemble_top3": args.w_top3,
        "ensemble_top5": args.w_top5,
        "fp_strength": args.w_fp,
    }
    bundle = build_bundle(pred_dir, blend_weights=blend)

    combined_csv = out_dir / "combined_predictions.csv"
    combined_json = out_dir / "combined_predictions.json"
    bundle.wide.to_csv(combined_csv, index=False)
    combined_json.write_text(bundle_to_json(bundle), encoding="utf-8")
    logger.info("Wrote %s", combined_csv)
    logger.info("Wrote %s", combined_json)

    wide = bundle.wide
    scenarios_payload = {
        "blend_weights": bundle.blend_weights,
        "longshot_blend_weights": bundle.longshot_blend_weights,
        "rankings": {
            "composite": ranking_table(wide, "composite"),
            "longshot_index": ranking_table(wide, "longshot_index"),
            "ensemble_top3": ranking_table(wide, "ensemble_top3"),
            "ensemble_top5": ranking_table(wide, "ensemble_top5"),
            "fp_strength": ranking_table(wide, "fp_strength"),
        },
        "exacta": exacta_scenario(
            wide,
            top_n=args.exacta_top_n,
            max_tickets=args.exacta_max,
        ),
        "trifecta": trifecta_scenario(
            wide,
            top_n=args.trifecta_top_n,
            max_tickets=args.trifecta_max,
        ),
        "superfecta": superfecta_scenario(
            wide,
            top_n=args.superfecta_top_n,
            max_tickets=args.superfecta_max,
        ),
    }
    scen_path = out_dir / "scenarios.json"
    scen_path.write_text(json.dumps(scenarios_payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s", scen_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
