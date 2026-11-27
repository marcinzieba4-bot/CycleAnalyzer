#!/usr/bin/env python3
"""Extract every edition's full model output into flat tables (point-in-time).

    python scripts/strategy_extract.py            # all editions under data/retro/

Re-runs the published model on each edition's retained inputs
(data/retro/<date>/*.csv + evidence.json), so the tables hold exactly what each
page knew on its date: all 23 FX scores with their five engines, the three
crosses, every curve call, context verdicts, policy stances, danger flags and
the global pack. Each edition's crosses are checked against its published page.

Output: data/strategy/{fx,crosses,curves,context,stances,editions}.csv
"""
from __future__ import annotations

import html
import json
import re
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "strategy"


def page_crosses(d: str) -> list[tuple[str, str, float]]:
    p = ROOT / "reports/retro/site" / f"{d}.html"
    if not p.exists():
        return []
    s = re.sub(r'src="data:image[^"]+"', "", p.read_text())
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))
    return [(m[1], m[2], float(m[3])) for m in
            re.finditer(r"Long ([A-Z]{3}) / short ([A-Z]{3}) — edge ([+-][\d.]+)\.", t)][:3]


def page_plays(d: str) -> list[str]:
    p = ROOT / "reports/retro/site" / f"{d}.html"
    if not p.exists():
        return []
    s = p.read_text()
    return [html.unescape(m) for m in
            re.findall(r'<div class="rank">PLAY \d</div><h3>(.*?)</h3>', s)]


def one(d: str) -> dict:
    warnings.filterwarnings("ignore")
    from cycle_analyzer.retro.editions import make_edition
    from cycle_analyzer.retro.benchmarks import targets_for
    from cycle_analyzer.analysis import run

    ed = make_edition(date.fromisoformat(d))
    src = ROOT / "data/retro" / d
    panels = {k: pd.read_csv(src / f"{k}.csv", index_col=0, parse_dates=True)
              for k in ["cli", "cpi", "policy", "reer", "y10"] if (src / f"{k}.csv").exists()}
    ev = json.loads((src / "evidence.json").read_text())
    snap = {cc: p["current"] for cc, p in ev["policy"].items()}
    res = run(panels, snapshot=snap, anchor=ed.anchor,
              retro={"edition": d, "cutoff_utc": ed.cutoff_iso, "reconstructed": "-"},
              targets=targets_for(ed))

    fx = []
    for rank, f in enumerate(res.fx, 1):
        clk = res.clocks.get(f.cc)
        st = res.stances.get(f.cc)
        rv = (res.reer_ctx or {}).get(f.cc)
        fx.append(dict(edition=d, rank=rank, cc=f.cc, ccy=f.ccy, carry=f.carry, cycle=f.cycle,
                       valuation=f.valuation, momentum=f.momentum, penalty=f.penalty,
                       total=round(float(f.total), 3),
                       policy=st.policy if st else None, infl_gap=st.infl_gap if st else None,
                       direction=st.direction if st else None,
                       phase=clk.phase if clk else None, heading=clk.heading if clk else None,
                       eta=clk.months_to_next if clk else None,
                       reer_verdict=rv.verdict if rv else None))
    crosses = [dict(edition=d, slot=i + 1, long=x["long"], short=x["short"], edge=x["edge"],
                    carry_pp=x["carry_pp"]) for i, x in enumerate(res.crosses)]
    curves = [dict(edition=d, cc=c.cc, slope=round(float(c.slope), 3), slope_z=round(float(c.slope_z), 3),
                   half_life=round(float(c.half_life), 1), phase=c.phase, call=c.direction,
                   stars=c.conviction, verdict=c.context_verdict) for c in res.curves]
    ctx = []
    for fam, dct in (("inflation", res.infl_ctx), ("slope", res.slope_ctx), ("reer", res.reer_ctx)):
        for cc, v in (dct or {}).items():
            if v.verdict != "NONE":
                ctx.append(dict(edition=d, cc=cc, family=fam, z=round(float(v.z), 3),
                                turning=v.turning, retraced=round(float(v.retraced), 3),
                                context=round(float(v.context), 3), verdict=v.verdict))
    stances = [dict(edition=d, cc=cc, policy=s.policy, d6=s.d6, real_rate=s.real_rate,
                    real_gap=s.real_gap, infl_gap=s.infl_gap, infl_mom=s.infl_mom,
                    direction=s.direction, labels="|".join(s.labels)) for cc, s in res.stances.items()]
    phases = pd.Series([c.phase for c in res.clocks.values()]).value_counts().to_dict()
    dirs = pd.Series([s.direction for s in res.stances.values()]).value_counts().to_dict()
    pub = page_crosses(d)
    mine = [(x["long"], x["short"], x["edge"]) for x in res.crosses]
    edrow = dict(edition=d, anchor=str(ed.anchor), n_clocks=len(res.clocks),
                 overheating=phases.get("Overheating", 0), goldilocks=phases.get("Goldilocks", 0),
                 stagflation=phases.get("Stagflation", 0), disinflation=phases.get("Disinflation", 0),
                 hiking=dirs.get("hiking", 0), cutting=dirs.get("cutting", 0), on_hold=dirs.get("on hold", 0),
                 safe="|".join(res.safe_list()),
                 plays=" || ".join(page_plays(d)),
                 crosses_match_page=(pub == mine) if pub else None)
    return dict(fx=fx, crosses=crosses, curves=curves, context=ctx, stances=stances, editions=[edrow])


def main() -> None:
    dates = sorted(p.name for p in (ROOT / "data/retro").iterdir()
                   if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    OUT.mkdir(parents=True, exist_ok=True)
    tabs: dict[str, list] = {}
    with ProcessPoolExecutor() as ex:
        for d, r in zip(dates, ex.map(one, dates)):
            for k, v in r.items():
                tabs.setdefault(k, []).extend(v)
            print(d, "ok" if r["editions"][0]["crosses_match_page"] else "MISMATCH/none", flush=True)
    for k, v in tabs.items():
        pd.DataFrame(v).to_csv(OUT / f"{k}.csv", index=False)
    e = pd.DataFrame(tabs["editions"])
    print(len(e), "editions;", int(e.crosses_match_page.fillna(False).sum()), "match their published crosses")


if __name__ == "__main__":
    main()
