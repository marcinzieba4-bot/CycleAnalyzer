#!/usr/bin/env bash
# Weekly Cycle Monitor job: refresh data -> rebuild report -> publish to site.
# Run from anywhere; exits non-zero with a FAILED line on any error, prints
# "WEEKLY JOB OK" at the end. Git commit/push is intentionally NOT done here —
# the calling session commits with its own attribution after this succeeds.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== deps =="
python3 -c "import pandas, numpy, matplotlib" 2>/dev/null || pip install -q pandas numpy matplotlib
python3 -c "import boto3" 2>/dev/null || pip install -q boto3

echo "== refresh data + run models =="
python3 scripts/run_analysis.py --refresh

echo "== build html =="
python3 scripts/build_html.py

echo "== publish to site (archive rotation + upload + invalidation) =="
python3 scripts/site_publish.py --deploy

echo "== verify live =="
TODAY=$(date -u +%F)
ok=""
for i in 1 2 3 4 5; do
  if curl -s https://zembihf.xyz/research/cycle/latest.html | grep -q "report-date\" content=\"$TODAY\""; then
    ok=1; echo "VERIFIED: live report-date is $TODAY"; break
  fi
  echo "  not live yet (attempt $i), waiting 60s for CloudFront..."
  sleep 60
done
if [ -z "$ok" ]; then
  echo "FAILED: live report-date is not $TODAY after 5 attempts"
  exit 1
fi

echo "WEEKLY JOB OK ($TODAY)"
