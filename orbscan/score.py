"""Turn a scan into a 0-100 safety score and a verdict. 100 = nothing suspicious found.
Every part is a straight line between a level where it costs nothing and a level where it costs its full weight."""

# name: (weight, no penalty at or below, full penalty at or above)
RULES = {
    "cluster_impact": (25, 0.10, 0.60),   # price drop if the biggest linked group sold
    "fresh_share":    (20, 0.10, 0.60),   # float held by brand-new wallets
    "transfer_share": (15, 0.02, 0.15),   # float received by transfer instead of bought
    "sniper_share":   (15, 0.02, 0.20),   # float still held by wallets that bought in the launch slot
    "top10_share":    (10, 0.25, 0.70),   # float held by the ten biggest wallets
    "dev_share":      (15, 0.03, 0.15),   # float the dev still holds
}
BANDS = [(80, "CLEAN"), (60, "OK"), (40, "RISKY"), (0, "DANGER")]
SERIAL_MIN_LAUNCHES, SERIAL_MAX_GRAD = 10, 0.05     # full history from the chain
LOCAL_SERIAL_MIN = 3                               # our own record: earlier launches by this wallet, none got traction


def penalty(x, weight, lo, hi):
    if x is None or x <= lo:
        return 0.0
    if x >= hi:
        return float(weight)
    return weight * (x - lo) / (hi - lo)


def metrics(s):
    H = [h for h in s["holders"] if not h.get("unread")]
    top = s["clusters"][0] if s["clusters"] else None
    return {
        "cluster_impact": top["impact"] if top else 0.0,
        "cluster_share": top["share"] if top else 0.0,
        "cluster_wallets": len(top["wallets"]) if top else 0,
        "fresh_share": sum(h["share"] for h in H if h.get("fresh") and not h["is_dev"]),
        "transfer_share": sum(h["share"] for h in H if h.get("acquired") == "transfer"),
        "sniper_share": sum(h["share"] for h in H if h.get("sniper")),
        "top10_share": sum(sorted((h["share"] for h in s["holders"]), reverse=True)[:10]),
        "dev_share": sum(h["share"] for h in s["holders"] if h["is_dev"]),
        "max_wallet": max([h["share"] for h in s["holders"] if not h["is_dev"]] or [0.0]),
        "unread": sum(1 for h in s["holders"] if h.get("unread")),
        "holders": len(s["holders"]),
    }


def verdict(s):
    m = metrics(s)
    parts = {k: round(penalty(m[k], *RULES[k]), 1) for k in RULES}
    score = round(100 - sum(parts.values()))
    flags, caps = [], []
    if m["cluster_impact"] >= 0.5 and m["cluster_wallets"] >= 2:
        flags.append(f"linked group of {m['cluster_wallets']} wallets could drop the price {m['cluster_impact']:.0%}")
    if m["fresh_share"] >= 0.7:
        flags.append(f"{m['fresh_share']:.0%} of float sits in brand-new wallets")
    if m["max_wallet"] >= 0.50:
        flags.append(f"one wallet holds {m['max_wallet']:.0%} of float")
    if m["sniper_share"] >= 0.30:
        flags.append(f"launch-slot snipers still hold {m['sniper_share']:.0%} of float")
    if m["dev_share"] >= 0.25:
        flags.append(f"the dev still holds {m['dev_share']:.0%} of float")
    if m["transfer_share"] >= 0.20:
        flags.append(f"{m['transfer_share']:.0%} of float was handed out, not bought")
    ch = s.get("creator_history")
    if ch and ch.get("source") == "local":
        if ch["launched"] >= LOCAL_SERIAL_MIN and ch["graduated"] == 0:
            flags.append(f"serial creator: {ch['launched']} earlier launches since we started watching, none got traction")
    elif ch and ch["launched"] >= SERIAL_MIN_LAUNCHES and ch["graduated"] < SERIAL_MAX_GRAD * ch["launched"]:
        flags.append(f"serial creator: {ch['launched']} launches, {ch['graduated']} graduated")
    if m["unread"] >= 5:
        caps.append(f"{m['unread']} wallets could not be read")
    if ch is None:
        caps.append("creator history not available")
    if caps and not flags:
        score = min(score, 79)          # never CLEAN on a partial read
    band = "DANGER" if flags else next(b for t, b in BANDS if score >= t)
    if m["holders"] == 0:
        band, score = "EMPTY", None       # nobody outside the curve and pools holds it: nothing to judge
    return {"score": score, "verdict": band, "parts": parts, "metrics": m, "flags": flags, "caps": caps}
