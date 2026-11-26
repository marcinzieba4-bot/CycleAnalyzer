#!/usr/bin/env python3
"""EX-POST scorecard of retrospective editions (uses later data by design).

    python scripts/retro_scorecard.py 2019-01-06 2019-01-20 ...

Not part of any edition: each edition is point-in-time; this script asks how its
calls performed afterwards.

  FX crosses: long A / short B entered at the BIS daily USD rate of the last
  business day before the edition Sunday, held 3 months (91 days), return =
  spot change of A vs B + policy-rate differential stated on the page x 91/365.
  Curve calls: change of (10y yield - policy rate), monthly, from the edition's
  month to 3 months later; a steepener scores the change, a flattener its negative.
"""
import csv, io, json, re, subprocess, sys, html
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cycle_analyzer.universe import COUNTRIES  # noqa: E402

W = ROOT / "data" / "retro_cache" / "scorecard"; W.mkdir(parents=True, exist_ok=True)
CACHE = W / "score_cache"; CACHE.mkdir(exist_ok=True)
BY_CCY = {c.ccy: cc for cc, c in COUNTRIES.items()}
NAME = {c.name: cc for cc, c in COUNTRIES.items()}


def get(url, name):
    f = CACHE / name
    if not f.exists():
        b = subprocess.run(["curl", "-sS", "--fail", "-m", "120", url], capture_output=True, check=True).stdout
        f.write_bytes(b)
    return f.read_text()


def bis(flow, key, start="2018-06-01", end="2020-06-30"):
    t = get(f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}?format=csv"
            f"&startPeriod={start}&endPeriod={end}", f"{flow}_{key}.csv")
    rows = [r for r in csv.DictReader(io.StringIO(t)) if r.get("OBS_VALUE")]
    return pd.Series({r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows}).sort_index()


def fx(cc):           # USD per unit of currency
    if cc == "US":
        return None
    s = bis("WS_XRU", f"D.{cc}.{COUNTRIES[cc].ccy}.A")
    s.index = pd.to_datetime(s.index)
    return 1.0 / s


def at(s, d, before=True):
    d = pd.Timestamp(d)
    x = s[s.index < d] if before else s[s.index >= d]
    return float(x.iloc[-1] if before else x.iloc[0])


def page_text(p):
    s = p.read_text()
    s = re.sub(r'src="data:image[^"]+"', "", s)
    s = re.sub(r"<style>.*?</style>", "", s, flags=re.S)
    return s


def crosses(s):
    t = html.unescape(re.sub(r"<[^>]+>", " ", s))
    t = re.sub(r"\s+", " ", t)
    out = []
    for m in re.finditer(r"Long ([A-Z]{3}) / short ([A-Z]{3}) — edge ([+-][\d.]+)\. buy .*?differential ([+-][\d.]+)pp", t):
        out.append({"long": m[1], "short": m[2], "edge": float(m[3]), "carry_pp": float(m[4])})
    return out


def curves(s):
    out = []
    for m in re.finditer(r'<tr><td class="name">([^<]+)</td><td class="num">([+-][\d.]+)pp</td>'
                         r'<td class="num">([^<]+)</td><td class="num">[^<]*</td><td>([^<]+)</td>'
                         r'<td><span class="tag \w+">(\w+) (★+)</span>', s):
        out.append({"cc": NAME[html.unescape(m[1])], "slope": float(m[2]), "z": m[3],
                    "phase": m[4], "call": m[5], "stars": len(m[6])})
    return out


def main(dates):
    pol, y10 = {}, {}
    rows_fx, rows_cv = [], []
    for d in dates:
        D = date.fromisoformat(d)
        s = page_text(ROOT / "reports/retro/site" / f"{d}.html")
        for x in crosses(s)[:3]:
            a, b = BY_CCY[x["long"]], BY_CCY[x["short"]]
            fa, fb = fx(a), fx(b)
            exit_d = D + timedelta(days=91)
            ra = np.log(at(fa, exit_d) / at(fa, D)) if fa is not None else 0.0
            rb = np.log(at(fb, exit_d) / at(fb, D)) if fb is not None else 0.0
            spot = (ra - rb) * 100
            carry = x["carry_pp"] * 91 / 365
            rows_fx.append({"edition": d, "trade": f"{x['long']}/{x['short']}", "edge": x["edge"],
                            "spot_pct": round(spot, 2), "carry_pct": round(carry, 2),
                            "total_pct": round(spot + carry, 2)})
        for c in curves(s):
            if c["call"] == "neutral" or c["stars"] < 2:
                continue
            cc = c["cc"]
            if cc not in pol:
                pol[cc] = bis("WS_CBPOL", f"M.{cc}")
                fid = COUNTRIES[cc].fred_10y
                t = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fid}&cosd=2018-06-01&coed=2020-06-01", f"{fid}.csv")
                r = [l.split(",") for l in t.strip().splitlines()[1:]]
                y10[cc] = pd.Series({k[:7]: float(v) for k, v in r if v not in ("", ".")})
            m0 = pd.Period(D, freq="M"); m3 = m0 + 3
            try:
                sl0 = y10[cc][str(m0)] - pol[cc][str(m0)]
                sl3 = y10[cc][str(m3)] - pol[cc][str(m3)]
            except KeyError:
                continue
            chg = (sl3 - sl0) * (1 if c["call"] == "steepener" else -1)
            rows_cv.append({"edition": d, "cc": cc, "call": c["call"], "stars": c["stars"],
                            "slope_chg_in_favour_pp": round(chg, 2)})
    f, c = pd.DataFrame(rows_fx), pd.DataFrame(rows_cv)
    f.to_csv(W / "score_fx.csv", index=False); c.to_csv(W / "score_curves.csv", index=False)
    print("FX crosses (3m hold):", len(f), "trades; hit rate", f"{(f.total_pct > 0).mean():.0%};",
          "mean", f"{f.total_pct.mean():+.2f}%", "median", f"{f.total_pct.median():+.2f}%")
    top = f.groupby("edition").head(1)
    print("  top cross only:", len(top), "hit", f"{(top.total_pct > 0).mean():.0%}", "mean", f"{top.total_pct.mean():+.2f}%")
    print("  by trade:\n", f.groupby("trade").total_pct.agg(["count", "mean"]).sort_values("count", ascending=False).head(12).round(2))
    print("  by half:", f.assign(h=f.edition.str[5:7].astype(int).le(6).map({True: "H1", False: "H2"})).groupby("h").total_pct.agg(["count", "mean", lambda s: (s > 0).mean()]).round(2))
    if len(c):
        print("Curve calls >=2 stars (3m):", len(c), "hit", f"{(c.slope_chg_in_favour_pp > 0).mean():.0%}",
              "mean", f"{c.slope_chg_in_favour_pp.mean():+.2f}pp")
        print(c.groupby(["cc", "call"]).slope_chg_in_favour_pp.agg(["count", "mean"]).sort_values("count", ascending=False).head(12).round(2))
        print(c.groupby("stars").slope_chg_in_favour_pp.agg(["count", "mean", lambda s: (s > 0).mean()]).round(2))


if __name__ == "__main__":
    main(sys.argv[1:])
