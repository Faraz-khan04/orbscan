"""Current price in SOL per token: the bonding curve while it trades there, DexScreener once it has graduated."""
import logging

from . import config
from .net import RateLimiter, http_json
from .pump import WSOL, decode_curve

log = logging.getLogger("prices")
_dex_limit = RateLimiter(3)


def dex_prices(mints):
    out = {}
    for i in range(0, len(mints), 30):
        try:
            pairs = http_json(config.DEX_URL + ",".join(mints[i:i + 30]), limiter=_dex_limit, tries=3) or []
        except Exception as e:
            log.warning("dexscreener: %s", e)
            continue
        best = {}
        for p in pairs:
            if (p.get("quoteToken") or {}).get("address") != WSOL or not p.get("priceNative"):
                continue
            m = p["baseToken"]["address"]
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if m not in best or liq > best[m][0]:
                best[m] = (liq, float(p["priceNative"]))
        out.update({m: v[1] for m, v in best.items()})
    return out


def prices(rpc, items):
    """items: [(mint, curve)] -> {mint: (price, graduated)}"""
    out, grad = {}, []
    accs = rpc.multiple_accounts([c for _, c in items])
    for (mint, _), acc in zip(items, accs):
        c = decode_curve(acc["data"]) if acc else None
        if not c:
            continue
        if c["complete"]:
            grad.append(mint)
        else:
            out[mint] = (c["price"], 0)
    for m, p in dex_prices(grad).items():
        out[m] = (p, 1)
    return out
