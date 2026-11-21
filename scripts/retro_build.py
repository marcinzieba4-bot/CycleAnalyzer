#!/usr/bin/env python3
"""Build (and optionally publish) retrospective point-in-time editions.

    python scripts/retro_build.py 2025-01-05 2025-01-19          # build only
    python scripts/retro_build.py --range 2025-01-01 2025-02-28 --every 14
    python scripts/retro_build.py ... --deploy                    # + upload

Each edition uses only information available before 00:00 Europe/Warsaw on
its date (see cycle_analyzer/retro). Outputs:

    data/retro/<date>/          exact model inputs (CSV) + evidence.json
    reports/retro/<date>/       charts + cycle_monitor.html
    reports/retro/site/<date>.html   site-wrapped page

--deploy uploads each page to /research/cycle/archive/<date>.html, never
touches latest.html, refuses to overwrite an existing archive page unless
--overwrite is given, rebuilds the archive index and invalidates CloudFront.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cycle_analyzer.retro.editions import make_edition, biweekly_sundays   # noqa: E402
from cycle_analyzer.retro import panels as P                               # noqa: E402
from cycle_analyzer.retro.evidence_html import render as render_evidence   # noqa: E402
from cycle_analyzer.analysis import run                                    # noqa: E402
from cycle_analyzer.charts import render_all                               # noqa: E402
import build_html                                                          # noqa: E402
import site_publish                                                        # noqa: E402


def build_one(d: date, reconstructed: str) -> Path:
    ed = make_edition(d)
    print(f"== {ed.iso}: cutoff {ed.cutoff_iso}, ALFRED vintage {ed.alfred_vintage}, "
          f"anchor {ed.anchor}")
    panels, ev = P.build(ed, verbose=False)
    P.save(ed, panels, ev)
    snapshot = {cc: p.current for cc, p in ev.policy.items()}
    ctx = {"edition": ed.iso, "cutoff_utc": ed.cutoff_iso, "reconstructed": reconstructed}
    res = run(panels, snapshot=snapshot, anchor=ed.anchor, retro=ctx)
    ctx["evidence_html"] = render_evidence(ed, ev, res, reconstructed)
    outdir = ROOT / "reports" / "retro" / ed.iso
    charts = render_all(res, outdir / "charts")
    html_path = outdir / "cycle_monitor.html"
    build_html.build(res, outdir / "charts", html_path)
    meta = f'<meta name="retrospective-cutoff" content="{ed.cutoff_iso}">\n'
    site = site_publish.wrap(ed.iso, src_path=html_path, extra_meta=meta)
    site_path = ROOT / "reports" / "retro" / "site" / f"{ed.iso}.html"
    site_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.write_text(site)
    print(f"   {len(res.clocks)} clocks, {len(res.standouts)} standouts, "
          f"{len(res.curves)} curve calls -> {site_path.relative_to(ROOT)}")
    return site_path


def deploy(pages: list[Path], overwrite: bool) -> None:
    import boto3
    key_id = os.environ.get("AWS_Key") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_Pass") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    sess = boto3.Session(aws_access_key_id=key_id, aws_secret_access_key=secret)
    s3 = sess.client("s3")
    B, PRE = site_publish.BUCKET, site_publish.PREFIX
    existing = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{PRE}/archive/"):
        existing |= {o["Key"] for o in page.get("Contents", [])}
    for p in pages:
        key = f"{PRE}/archive/{p.name}"
        if key in existing and not overwrite:
            raise SystemExit(f"refusing to overwrite existing {key} (use --overwrite)")
    for p in pages:
        key = f"{PRE}/archive/{p.name}"
        s3.put_object(Bucket=B, Key=key, Body=p.read_bytes(), **site_publish.HTML_HEADERS)
        existing.add(key)
        print(f"uploaded {key} ({p.stat().st_size / 1e6:.2f} MB)")
    keys = sorted(k for k in existing if k.endswith(".html"))
    s3.put_object(Bucket=B, Key=f"{PRE}/index.html",
                  Body=site_publish.build_index(keys).encode(), **site_publish.HTML_HEADERS)
    print(f"index.html rebuilt with {len(keys)} archived reports (latest.html untouched)")
    items = ["/research/cycle/index.html"] + [f"/research/cycle/archive/{p.name}" for p in pages]
    inv = sess.client("cloudfront").create_invalidation(
        DistributionId=site_publish.DISTRIBUTION,
        InvalidationBatch={"Paths": {"Quantity": len(items), "Items": items},
                           "CallerReference": f"cycle-retro-{int(time.time())}"})
    print("cloudfront invalidation:", inv["Invalidation"]["Id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dates", nargs="*", help="edition Sundays (YYYY-MM-DD)")
    ap.add_argument("--range", nargs=2, metavar=("START", "END"))
    ap.add_argument("--every", type=int, default=14, help="days between editions (7 or 14)")
    ap.add_argument("--reconstructed", default=date.today().isoformat())
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    ds = [date.fromisoformat(x) for x in a.dates]
    if a.range:
        s, e = (date.fromisoformat(x) for x in a.range)
        ds += biweekly_sundays(s, e, step_days=a.every)
    if not ds:
        ap.error("no editions given")
    pages = [build_one(d, a.reconstructed) for d in sorted(set(ds))]
    if a.deploy:
        deploy(pages, a.overwrite)


if __name__ == "__main__":
    main()
