#!/usr/bin/env python3
"""Look-ahead audit for retrospective editions.

For each edition it re-checks, from the retained inputs and evidence:
  1. every ledger source was available before the cutoff
     (git commit times, ALFRED vintage dates incl. the served vintage column,
      original-release publication dates)
  2. no input observation is dated at or after the edition month
  3. every policy snapshot level took effect on or before the last day wholly
     before the cutoff, and every cited announcement was made before it
  4. the published page mentions no calendar date after the cutoff other than
     the declared reconstruction date
  5. the retained CSV inputs are exactly what the evidence describes
     (last observation per family/economy)

    python scripts/retro_audit.py 2025-01-05 2025-01-19 ...
Exit status 1 if any check fails.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cycle_analyzer.retro.editions import make_edition          # noqa: E402
from cycle_analyzer.retro import sources as S                    # noqa: E402

SOURCES = json.loads((ROOT / "data/retro/announcement_sources.json").read_text())


def audit(d: date) -> list[str]:
    ed = make_edition(d)
    base = ROOT / "data" / "retro" / ed.iso
    ev = json.loads((base / "evidence.json").read_text())
    cut = ed.cutoff_utc
    fails, ok = [], 0

    def check(cond: bool, msg: str):
        nonlocal ok
        if cond:
            ok += 1
        else:
            fails.append(msg)

    # 1. sources -------------------------------------------------------------
    for k, e in ev["ledger"].items():
        if e["kind"] == "dbnomics-git":
            t = datetime.fromisoformat(e["available_by"])
            check(t < cut, f"{k}: commit {t} not before cutoff {cut}")
        elif e["kind"] == "alfred":
            vd = date.fromisoformat(e["url"].split("vintage_date=")[1][:10])
            check(vd <= ed.alfred_vintage, f"{k}: vintage {vd} after {ed.alfred_vintage}")
            raw, _, _ = S.cached_get(e["url"])
            hdr = raw.decode().splitlines()[0]
            m = re.search(r"_(\d{8})", hdr)
            if m:
                served = datetime.strptime(m.group(1), "%Y%m%d").date()
                check(served <= ed.alfred_vintage,
                      f"{k}: ALFRED served vintage {served} after {ed.alfred_vintage}")
            else:
                fails.append(f"{k}: cannot read ALFRED vintage column from header {hdr!r}")
        elif e["kind"] == "repo-git":
            t = datetime.fromisoformat(e["available_by"].replace("Z", "+00:00"))
            check(t < cut, f"{k}: repository commit {t} not before cutoff {cut}")
            _, sha, path = e["url"].split(":", 2)
            import hashlib
            import subprocess
            raw = subprocess.run(["git", "-C", str(ROOT), "show", f"{sha}:{path}"],
                                 capture_output=True).stdout
            check(hashlib.sha256(raw).hexdigest() == e["sha256"],
                  f"{k}: bytes at {sha[:12]}:{path} do not match the recorded SHA-256")
            ct = subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%cI", sha],
                                capture_output=True, text=True).stdout.strip()
            check(bool(ct) and datetime.fromisoformat(ct) < cut,
                  f"{k}: git reports commit time {ct!r}, not before cutoff")
        elif e["kind"] == "original-release":
            rd = date.fromisoformat(e["available_by"][:10])
            check(rd <= ed.last_eligible_day, f"{k}: released {rd} not before cutoff")
        elif e["kind"] == "bis-current":
            end = date.fromisoformat(e["url"].split("endPeriod=")[1][:10])
            check(end <= ed.last_eligible_day,
                  f"{k}: decision-history download extends to {end}, after the cutoff day")
            raw, _, _ = S.cached_get(e["url"])
            last = max(r[0] for r in S.parse_bis_csv(raw)) if raw else ""
            check(not last or date.fromisoformat(last[:10]) <= ed.last_eligible_day,
                  f"{k}: retained bytes contain {last}, after the cutoff day")
    # 2. observation months ---------------------------------------------------
    for cc, fam in ev["obs"].items():
        for f, last in fam.items():
            if last:
                check(pd.Period(last, freq="M") <= ed.anchor,
                      f"obs {f}/{cc} {last} not before edition month")
    for f in ("policy", "cpi", "reer", "cli", "y10"):
        df = pd.read_csv(base / f"{f}.csv", index_col=0, parse_dates=True)
        mx = df.index.max().to_period("M")
        check(mx <= ed.anchor, f"{f}.csv extends to {mx}")
        for cc in df.columns:
            s = df[cc].dropna()
            want = ev["obs"].get(cc, {}).get(f)
            check(want is None or str(s.index.max().to_period("M")) == want,
                  f"{f}.csv/{cc} last {s.index.max():%Y-%m} != evidence {want}")
    # 3. policy snapshot --------------------------------------------------------
    for cc, p in ev["policy"].items():
        es = p["effective_since"]
        if re.match(r"\d{4}-\d{2}-\d{2}$", es):
            check(date.fromisoformat(es) <= ed.last_eligible_day,
                  f"policy {cc} effective {es} after {ed.last_eligible_day}")
    for a in ev["announcements"]:
        check(date.fromisoformat(a["effective"]) <= ed.last_eligible_day,
              f"announcement {a} effective after cutoff day")
        src = SOURCES.get(f"{a['cc']}|{a['effective']}")
        check(src is not None, f"announcement {a['cc']} {a['effective']} has no cited source")
        if src:
            check(date.fromisoformat(src["announced"]) <= ed.last_eligible_day,
                  f"announcement {a['cc']} announced {src['announced']} after cutoff day")
    # 4. page text dates ------------------------------------------------------
    page = (ROOT / "reports" / "retro" / "site" / f"{ed.iso}.html").read_text()
    txt = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "", page)
    txt = re.sub(r'href="[^"]*"', "", txt)
    recon = re.search(r"Reconstructed (\d{4}-\d{2}-\d{2})", txt)
    allowed = ({recon.group(1)} if recon else set()) | {ed.iso}   # edition label itself
    for m in re.finditer(r"(?<![\d.])(20\d{2})-(\d{2})(?:-(\d{2}))?(?![\d])", txt):
        y, mo, dd = m.group(1), m.group(2), m.group(3)
        if dd:
            try:
                dt = date(int(y), int(mo), int(dd))
            except ValueError:
                continue
            if m.group(0) in allowed:
                continue
            check(dt <= ed.last_eligible_day, f"page mentions date {m.group(0)} after cutoff")
        else:
            try:
                p = pd.Period(f"{y}-{mo}", freq="M")
            except Exception:  # noqa: BLE001
                continue
            if any(m.group(0) in a for a in allowed):
                continue
            check(p <= pd.Period(ed.date, freq="M"),
                  f"page mentions month {m.group(0)} after edition month")
    # no year after the edition year anywhere except the reconstruction stamp
    stripped = re.sub(r"Reconstructed( on)? \d{4}-\d{2}-\d{2}", "", txt)
    for yr in range(ed.date.year + 1, ed.date.year + 3):
        n = len(re.findall(rf"(?<!\d){yr}(?!\d)", stripped))
        check(n == 0, f"page mentions {yr} outside the reconstruction stamp ({n}x)")
    # written-out dates ("12 November 2025", "March 2026") must not be later either
    MON = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
    for m in re.finditer(r"(?:(\d{1,2}) )?(" + "|".join(MON) + r") (20\d{2})", stripped):
        dd, mon, yy = m.group(1), MON.index(m.group(2)) + 1, int(m.group(3))
        if dd:
            try:
                dt = date(yy, mon, int(dd))
            except ValueError:
                continue
            if dt == ed.date:          # the edition date itself ("before 13 September …")
                continue
            check(dt <= ed.last_eligible_day, f"page mentions date {m.group(0)!r} after cutoff")
        else:
            check(pd.Period(f"{yy}-{mon:02d}", freq="M") <= pd.Period(ed.date, freq="M"),
                  f"page mentions month {m.group(0)!r} after edition month")
    print(f"{ed.iso}: {ok} checks passed, {len(fails)} failed")
    for f in fails:
        print("   FAIL", f)
    return fails


def main() -> None:
    ds = [date.fromisoformat(x) for x in sys.argv[1:]]
    bad = sum(len(audit(d)) for d in ds)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
