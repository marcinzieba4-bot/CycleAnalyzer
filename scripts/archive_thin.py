#!/usr/bin/env python3
"""Thin the published Cycle Monitor archive to a biweekly Sunday cadence.

The biweekly grid is every 14 days from ANCHOR (2025-01-05, the first
retrospective edition). For reports dated after --after, any archive page
whose date is off that grid is removed from the site; latest.html is
replaced by the newest on-grid archive page if its own report-date is off
the grid (the next on-grid weekly run then rotates normally).

Nothing is lost: every removed page (and the previous latest.html and
index.html) is first copied server-side to

    s3://s3bucketmz/veerock-site/backups/cycle-archive-thinned-<UTC stamp>/

which is outside the public static/ prefix. Restore = copy back.

    python scripts/archive_thin.py                 # dry run: print the plan
    python scripts/archive_thin.py --apply         # back up, delete, re-index
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_publish as SP  # noqa: E402

ANCHOR = date(2025, 1, 5)
BACKUP_ROOT = "veerock-site/backups"


def on_grid(d: date) -> bool:
    return (d - ANCHOR).days % 14 == 0 and d.weekday() == 6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", default="2025-09-30",
                    help="only thin reports dated after this day")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    after = date.fromisoformat(a.after)

    import boto3
    sess = boto3.Session(
        aws_access_key_id=os.environ.get("AWS_Key") or os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_Pass") or os.environ.get("AWS_SECRET_ACCESS_KEY"))
    s3 = sess.client("s3")
    B, PRE = SP.BUCKET, SP.PREFIX

    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=f"{PRE}/archive/"):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".html")]
    dated = {date.fromisoformat(k.rsplit("/", 1)[1][:-5]): k for k in keys}
    remove = sorted(d for d in dated if d > after and not on_grid(d))
    keep = sorted(d for d in dated if d not in remove)

    latest_key = f"{PRE}/latest.html"
    latest_date = date.fromisoformat(SP._report_date_of(
        s3.get_object(Bucket=B, Key=latest_key)["Body"].read()))
    new_latest = None
    if latest_date > after and not on_grid(latest_date):
        cands = [d for d in keep if d <= latest_date and on_grid(d)]
        new_latest = cands[-1] if cands else None

    print(f"archive pages: {len(dated)}; off-grid after {after}: {len(remove)}")
    for d in remove:
        print(f"  remove {d}")
    print(f"latest.html report-date {latest_date}: "
          + (f"off-grid -> replace with archive/{new_latest}.html" if new_latest
             else "on-grid (or before window) -> unchanged"))
    after_dates = [d for d in keep if d > after] + ([] if new_latest else [latest_date])
    gaps = sorted({(y - x).days for x, y in zip(after_dates, after_dates[1:])})
    print(f"after thinning: {len(after_dates)} reports after {after}; gaps (days) {gaps}")
    if not a.apply:
        print("dry run; pass --apply to execute")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bk = f"{BACKUP_ROOT}/cycle-archive-thinned-{stamp}"
    to_backup = [dated[d] for d in remove] + [latest_key, f"{PRE}/index.html"]
    for k in to_backup:
        dst = f"{bk}/{k[len(PRE) + 1:]}"
        s3.copy_object(Bucket=B, Key=dst, CopySource={"Bucket": B, "Key": k},
                       MetadataDirective="COPY")
        head = s3.head_object(Bucket=B, Key=dst)
        src = s3.head_object(Bucket=B, Key=k)
        if head["ContentLength"] != src["ContentLength"]:
            raise SystemExit(f"backup size mismatch for {k}; aborting before any delete")
    print(f"backed up {len(to_backup)} objects -> s3://{B}/{bk}/")

    if new_latest:
        s3.copy_object(Bucket=B, Key=latest_key,
                       CopySource={"Bucket": B, "Key": dated[new_latest]},
                       ContentType=SP.HTML_HEADERS["ContentType"],
                       CacheControl=SP.HTML_HEADERS["CacheControl"],
                       MetadataDirective="REPLACE")
        print(f"latest.html <- archive/{new_latest}.html")
    for d in remove:
        s3.delete_object(Bucket=B, Key=dated[d])
    print(f"deleted {len(remove)} off-grid archive pages")

    kept_keys = [dated[d] for d in keep]
    s3.put_object(Bucket=B, Key=f"{PRE}/index.html",
                  Body=SP.build_index(kept_keys).encode(), **SP.HTML_HEADERS)
    print(f"index.html rebuilt with {len(kept_keys)} archived reports")
    inv = sess.client("cloudfront").create_invalidation(
        DistributionId=SP.DISTRIBUTION,
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/research/cycle/*"]},
                           "CallerReference": f"cycle-thin-{int(time.time())}"})
    print("cloudfront invalidation:", inv["Invalidation"]["Id"])


if __name__ == "__main__":
    main()
