#!/usr/bin/env python3
"""Publish the cycle monitor to the veerock site with weekly archive rotation.

The live site serves the report inside the Research > Cycle Analyzer tab:

    /research/cycle/latest.html        the current weekly report
    /research/cycle/archive/<date>.html  every non-current report
    /research/cycle/index.html         archive index (anchors parsed by the
                                       site's React archive browser, same
                                       format as /reports/index.html)

What this script does with --deploy:
  1. Wraps reports/cycle_monitor.html for the site: full HTML skeleton,
     forced light theme, WHITE background (matching Daily Summary reports),
     async Google-Fonts link (never render-blocks the iframe), and a
     <meta name="report-date"> stamp.
  2. Rotation: if the deployed latest.html has a different report-date than
     the new one, the deployed copy is moved to archive/<its-date>.html —
     every non-current report lands in the Archive.
  3. Rebuilds index.html from the archive listing (grouped year/month).
  4. Uploads latest + archive + index and invalidates CloudFront.

Without --deploy it only writes the wrapped file locally
(reports/site/latest.html) for inspection.

Credentials: AWS_Key / AWS_Pass environment variables (as provisioned in
this environment) or a standard boto3 credential chain.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "s3bucketmz"
PREFIX = "veerock-site/static/research/cycle"
DISTRIBUTION = "E15IJW4438D21G"
HTML_HEADERS = {"ContentType": "text/html",
                "CacheControl": "public, max-age=60, must-revalidate"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def wrap(report_date: str) -> str:
    src = (ROOT / "reports" / "cycle_monitor.html").read_text()
    marker = '<div class="wrap">'
    i = src.find(marker)
    if i < 0:
        raise SystemExit("cycle_monitor.html: content marker not found")
    head, body = src[:i], src[i:]
    head = head.replace(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?',
        '<link rel="stylesheet" media="print" onload="this.media=\'all\'" '
        'href="https://fonts.googleapis.com/css2?')
    # White theme, as Daily Summary reports render: page and cards on white.
    white = "<style>:root{--bg:#ffffff;--surface:#ffffff}</style>"
    return ("<!doctype html>\n"
            f'<html lang="en" data-theme="light">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="report-date" content="{report_date}">\n'
            + head + white + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")


def _report_date_of(html: bytes) -> str | None:
    m = re.search(rb'<meta name="report-date" content="(\d{4}-\d{2}-\d{2})"', html)
    return m.group(1).decode() if m else None


def build_index(archive_keys: list[str]) -> str:
    """Archive index in the same shape the site's React browser parses."""
    dates = sorted((k.rsplit("/", 1)[-1][:-5] for k in archive_keys), reverse=True)
    lines = ["<html>", '<head><meta charset="utf-8">'
             "<title>DM+EM Cycle Monitor — Archive</title></head>",
             '<body style="font-family:Arial,sans-serif;max-width:600px;'
             'margin:40px auto;color:#222">',
             '  <h1 style="color:#1a1a2e">DM+EM Cycle Monitor</h1>',
             '  <p><a href="latest.html">View latest report</a></p>',
             '  <h2 style="margin-top:32px">Archive</h2>']
    by_year: dict[str, dict[str, list[str]]] = {}
    for d in dates:
        y, m, _ = d.split("-")
        by_year.setdefault(y, {}).setdefault(m, []).append(d)
    for y in sorted(by_year, reverse=True):
        lines.append(f'    <h3 style="color:#1a1a2e;border-bottom:1px solid #ddd;'
                     f'padding-bottom:4px;margin-top:24px">{y}</h3>')
        for m in sorted(by_year[y], reverse=True):
            lines.append(f'      <h4 style="color:#555;margin:14px 0 6px">'
                         f'{MONTHS[int(m) - 1]}</h4>')
            lines.append('      <ul style="line-height:1.8;margin:0">')
            for d in by_year[y][m]:
                lines.append(f'        <li><a href="archive/{d}.html">{d}</a></li>')
            lines.append("      </ul>")
    lines += ["</body>", "</html>"]
    return "\n".join(lines)


def deploy(wrapped: str, report_date: str) -> None:
    import boto3
    key_id = os.environ.get("AWS_Key") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_Pass") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    session = boto3.Session(aws_access_key_id=key_id, aws_secret_access_key=secret)
    s3 = session.client("s3")

    # 1. rotate the deployed latest into the archive if it is a different report
    latest_key = f"{PREFIX}/latest.html"
    try:
        cur = s3.get_object(Bucket=BUCKET, Key=latest_key)
        cur_bytes = cur["Body"].read()
        cur_date = _report_date_of(cur_bytes) or cur["LastModified"].strftime("%Y-%m-%d")
        if cur_date != report_date:
            arch_key = f"{PREFIX}/archive/{cur_date}.html"
            s3.put_object(Bucket=BUCKET, Key=arch_key, Body=cur_bytes, **HTML_HEADERS)
            print(f"archived previous report -> {arch_key}")
        else:
            print(f"deployed latest has the same report-date ({cur_date}); no rotation")
    except s3.exceptions.NoSuchKey:
        print("no deployed latest.html yet; nothing to archive")

    # 2. rebuild the archive index
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}/archive/"):
        keys += [o["Key"] for o in page.get("Contents", [])
                 if o["Key"].endswith(".html")]
    index_html = build_index(keys)
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}/index.html",
                  Body=index_html.encode(), **HTML_HEADERS)
    print(f"index.html rebuilt with {len(keys)} archived reports")

    # 3. upload the new latest
    s3.put_object(Bucket=BUCKET, Key=latest_key, Body=wrapped.encode(), **HTML_HEADERS)
    print(f"uploaded {latest_key} ({len(wrapped)/1e6:.2f} MB, report-date {report_date})")

    # 4. invalidate CloudFront
    cf = session.client("cloudfront")
    inv = cf.create_invalidation(
        DistributionId=DISTRIBUTION,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/research/cycle/*"]},
            "CallerReference": f"cycle-publish-{int(time.time())}",
        })
    print("cloudfront invalidation:", inv["Invalidation"]["Id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true",
                    help="rotate archive and upload to S3 + CloudFront")
    ap.add_argument("--date", default=date.today().isoformat(),
                    help="report date stamp (default: today)")
    args = ap.parse_args()

    wrapped = wrap(args.date)
    out = ROOT / "reports" / "site" / "latest.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(wrapped)
    print(f"wrote {out}")
    if args.deploy:
        deploy(wrapped, args.date)


if __name__ == "__main__":
    main()
