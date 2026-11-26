"""The honest test: for every token we flagged, what happened after the moment we could have bought it."""
import csv
import statistics as st
import time

from . import config

WINDOW = None


def outcomes(c, now=None, hours=None):
    now = now or time.time()
    hours = hours or config.TRACK_HOURS
    rows = c.execute("""SELECT t.mint, t.kind, t.start_ts, t.entry_price, s.verdict, s.score, l.symbol
                        FROM tracked t JOIN launches l ON l.mint=t.mint LEFT JOIN scans s ON s.mint=t.mint""").fetchall()
    out = []
    for r in rows:
        if not r["entry_price"]:
            continue
        end = r["start_ts"] + hours * 3600
        snaps = c.execute("SELECT ts, price FROM snaps WHERE mint=? AND ts>=? AND ts<=? AND price>0 ORDER BY ts",
                          (r["mint"], r["start_ts"], end)).fetchall()
        e = r["entry_price"]
        later = [s for s in snaps if s["ts"] > r["start_ts"] + 1]
        o = {"mint": r["mint"], "symbol": r["symbol"], "group": "baseline" if r["kind"] == "baseline" else (r["verdict"] or "?"),
             "score": r["score"], "entry": e, "snaps": len(later), "complete": now >= end,
             "peak": max([s["price"] for s in later] + [e]) / e, "r1h": None, "rend": None}
        h1 = [s for s in later if s["ts"] >= r["start_ts"] + 3600]
        if h1:
            o["r1h"] = h1[0]["price"] / e - 1
        if later and o["complete"]:
            o["rend"] = later[-1]["price"] / e - 1
        out.append(o)
    return out


def _pct(x):
    return "—" if x is None else f"{x * 100:+.0f}%"


def summarize(os_, cost=None):
    cost = config.ROUND_TRIP_COST if cost is None else cost
    done = [o for o in os_ if o["complete"] and o["rend"] is not None]
    s = {"n": len(os_), "done": len(done)}
    if not os_:
        return s
    s["peak2"] = sum(o["peak"] >= 2 for o in os_) / len(os_)
    s["peak5"] = sum(o["peak"] >= 5 for o in os_) / len(os_)
    s["peak10"] = sum(o["peak"] >= 10 for o in os_) / len(os_)
    r1 = [o["r1h"] for o in os_ if o["r1h"] is not None]
    s["med1h"] = st.median(r1) if r1 else None
    if done:
        s["med_end"] = st.median(o["rend"] for o in done)
        s["dead"] = sum(o["rend"] <= -0.8 for o in done) / len(done)
        hold = [(1 + o["rend"]) * (1 - cost) - 1 for o in done]
        tp = [(2 * (1 - cost) - 1) if o["peak"] >= 2 else h for o, h in zip(done, hold)]
        s["hold_mean"], s["hold_win"] = st.mean(hold), sum(h > 0 for h in hold) / len(hold)
        s["tp_mean"], s["tp_win"] = st.mean(tp), sum(t > 0 for t in tp) / len(tp)
    return s


GROUPS = ["baseline", "ALL SCANNED", "CLEAN", "OK", "RISKY", "DANGER", "EMPTY"]


def build(c, now=None):
    os_ = outcomes(c, now)
    scanned = [o for o in os_ if o["group"] != "baseline"]
    groups = {"baseline": [o for o in os_ if o["group"] == "baseline"], "ALL SCANNED": scanned}
    for g in GROUPS[2:]:
        groups[g] = [o for o in scanned if o["group"] == g]
    return os_, {g: summarize(v) for g, v in groups.items()}


def markdown(c, now=None):
    os_, S = build(c, now)
    n_launch = c.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
    n_scan = c.execute("SELECT COUNT(*) FROM scans WHERE error IS NULL").fetchone()[0]
    first = c.execute("SELECT MIN(created_ts) FROM launches").fetchone()[0]
    hrs = (time.time() - first) / 3600 if first else 0
    L = [f"# orbscan paper test — {time.strftime('%Y-%m-%d %H:%M')}",
         "", f"{n_launch} launches heard over {hrs:.1f} h · {n_scan} scanned after reaching {config.TRIGGER_SOL:g} SOL in their curve.",
         f"Entry = price when the scan finished. Costs assumed {config.ROUND_TRIP_COST:.0%} per round trip. Horizon {config.TRACK_HOURS:g} h.", "",
         "| group | tokens | finished | peak ≥2x | ≥5x | ≥10x | median 1h | median at end | dead (≤−80%) | hold: avg / win | TP 2x: avg / win |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in GROUPS:
        s = S[g]
        if not s["n"]:
            L.append(f"| {g} | 0 | | | | | | | | | |")
            continue
        L.append(f"| {g} | {s['n']} | {s['done']} | {s['peak2']:.0%} | {s['peak5']:.0%} | {s['peak10']:.0%} | {_pct(s['med1h'])} | "
                 f"{_pct(s.get('med_end'))} | {s['dead']:.0%} | {_pct(s['hold_mean'])} / {s['hold_win']:.0%} | {_pct(s['tp_mean'])} / {s['tp_win']:.0%} |"
                 if s["done"] else
                 f"| {g} | {s['n']} | 0 | {s['peak2']:.0%} | {s['peak5']:.0%} | {s['peak10']:.0%} | {_pct(s['med1h'])} | — | — | — | — |")
    best = sorted([o for o in os_ if o["group"] != "baseline"], key=lambda o: -o["peak"])[:3]
    if best:
        L += ["", "**The thread-style highlight reel** (what a promoter would post): " +
              ", ".join(f"${o['symbol'] or o['mint'][:6]} {o['peak']:.0f}x peak ({o['group']})" for o in best) +
              ". Compare it with the averages above."]
    L += ["", "Notes: peaks are sampled every few minutes, so real spikes can be higher and are rarely sellable at the top. "
          "TP 2x assumes the sell fills at exactly 2x. Small samples swing a lot: treat fewer than ~50 finished tokens per group as noise."]
    return "\n".join(L), os_


def write(c, md_path="report.md", csv_path="outcomes.csv"):
    md, os_ = markdown(c)
    open(md_path, "w", encoding="utf-8").write(md)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["mint", "symbol", "group", "score", "entry", "snaps", "complete", "peak", "r1h", "rend"])
        w.writeheader()
        w.writerows(os_)
    return md
