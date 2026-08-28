#!/usr/bin/env python3
"""End-to-end run: fetch (or use cache) -> models -> charts -> report.

Usage:
    python scripts/run_analysis.py            # use cached data
    python scripts/run_analysis.py --refresh  # re-download all series
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cycle_analyzer.data import load_panel          # noqa: E402
from cycle_analyzer.analysis import run             # noqa: E402
from cycle_analyzer.charts import render_all        # noqa: E402
from cycle_analyzer.report import build_report      # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download all series")
    ap.add_argument("--out", default="reports", help="output directory")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print("== loading data ==")
    panels = load_panel(refresh=args.refresh)
    print("== running models ==")
    res = run(panels)
    print(f"as of {res.asof}: {len(res.clocks)} clocks, "
          f"{len(res.standouts)} standouts, {len(res.curves)} curve calls")
    print("== rendering charts ==")
    charts = render_all(res, outdir / "charts")
    print("== writing report ==")
    build_report(res, {k: p.relative_to(outdir) for k, p in charts.items()}, outdir)
    print(f"done -> {outdir / 'cycle_monitor.md'}")


if __name__ == "__main__":
    main()
