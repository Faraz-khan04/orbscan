"""One scan of one token: who holds it, how they are linked, what the dev did. Returns a plain dict."""
import time

from . import config
from .cluster import build
from .pump import BURN, PUMP_AMM, PUMP_PROGRAM, SYSTEM, bonding_curve, decode_curve, sell_impact
from .txparse import fee_payer, funder_of, how_acquired, token_deltas

TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}


def _safe(fn, *a, default=None):
    try:
        return fn(*a)
    except Exception:
        return default


def early_buyers(rpc, mint, curve):
    """Read the mint's oldest transactions. Returns (dev, create_slot, {owner: first buy slot}, n_read)."""
    sigs, before, reached_start = [], None, False
    for _ in range(4):                     # up to 4,000 signatures back; older tokens are not our target
        page = rpc.signatures(mint, limit=1000, before=before)
        sigs += page
        if len(page) < 1000:
            reached_start = True
            break
        before = page[-1]["signature"]
    if not reached_start:                  # too busy to see the launch: no dev, no launch slot, no snipers
        return None, None, {}, 0
    oldest = [s for s in reversed(sigs) if not s.get("err")][:config.EARLY_TXS]
    dev, create_slot, first = None, None, {}
    for i, s in enumerate(oldest):
        tx = _safe(rpc.transaction, s["signature"])
        if not tx:
            continue
        if i == 0:
            dev, create_slot = fee_payer(tx), tx["slot"]
        for owner, d in token_deltas(tx, mint).items():
            if d > 0 and owner != curve and owner not in first:
                first[owner] = tx["slot"]
    return dev, create_slot, first, len(oldest)


def wallet_profile(rpc, wallet, token_account, mint, program_owned):
    p = {"wallet": wallet, "unread": False}
    try:
        sigs = rpc.signatures(wallet, limit=100)
        p["n_tx"] = len(sigs)
        oldest = sigs[-1] if sigs else None
        age_h = (time.time() - oldest["blockTime"]) / 3600 if oldest and oldest.get("blockTime") else None
        p["age_h"] = age_h
        p["fresh"] = len(sigs) < config.FRESH_MAX_TXS or (len(sigs) < 100 and age_h is not None and age_h < config.FRESH_MAX_AGE_H)
        p["funder"] = None
        if 0 < len(sigs) < 100:            # whole history is in hand, so the oldest tx is the funding one
            tx = rpc.transaction(oldest["signature"])
            p["funder"] = funder_of(tx, wallet) if tx else None
        tsigs = rpc.signatures(token_account, limit=100)
        p["acquired"], p["sender"] = "unknown", None
        for sig in list(reversed(tsigs))[:3]:      # the first one may only create the account
            tx = rpc.transaction(sig["signature"])
            if tx:
                p["acquired"], p["sender"] = how_acquired(tx, wallet, mint, program_owned)
                if p["acquired"] != "unknown":
                    break
    except Exception as e:
        p["unread"] = True
        p["error"] = str(e)[:200]
    return p


def scan(rpc, mint, curve=None, creator=None, history=None):
    """history: callable(creator) -> {launched, graduated, source} or None, supplied by the caller."""
    t0, calls0 = time.time(), rpc.calls
    curve = curve or bonding_curve(mint)
    supply = float(rpc.call("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    accts = rpc.token_accounts(mint)
    rows = sorted(({"token_account": a, "owner": o, "amount": amt} for a, o, amt in accts if amt > 0),
                  key=lambda r: -r["amount"])
    n_holders = len({r["owner"] for r in rows})
    rows = rows[:config.TOP_N + 10]          # the curve, pools and burns may sit among the biggest
    owners = sorted({r["owner"] for r in rows})
    kinds = rpc.multiple_accounts(owners, data_slice={"offset": 0, "length": 0})
    program_owned = set()
    for o, acc in zip(owners, kinds):
        if o == curve or o in BURN or (acc is not None and acc.get("owner") not in (SYSTEM,)):
            program_owned.add(o)       # curve, AMM pool, locker: not a holder
    cacc = rpc.multiple_accounts([curve])[0]
    curve_state = decode_curve(cacc["data"]) if cacc else None
    graduated = bool(curve_state and curve_state["complete"])

    pool_tokens = sum(r["amount"] for r in rows if r["owner"] in program_owned)
    float_tokens = max(supply - pool_tokens, 1e-9)
    # the reserve a seller would hit: the curve's virtual reserve before graduation, the biggest pool after
    if curve_state and not graduated:
        reserve = curve_state["vtok"] / 1e6
    else:
        reserve = max([r["amount"] for r in rows if r["owner"] in program_owned] or [0])

    dev, create_slot, first, n_early = early_buyers(rpc, mint, curve)
    creator = creator or (curve_state or {}).get("creator") or dev

    holders = []
    for r in rows:
        if r["owner"] in program_owned:
            continue
        p = wallet_profile(rpc, r["owner"], r["token_account"], mint, frozenset(program_owned))
        p.update(amount=r["amount"], share=r["amount"] / float_tokens, is_dev=r["owner"] in (dev, creator))
        p["early_slot"] = first.get(r["owner"])
        p["sniper"] = p["early_slot"] is not None and create_slot is not None and p["early_slot"] <= create_slot + 1 and not p["is_dev"]
        holders.append(p)
        if len(holders) >= config.TOP_N:
            break

    cl = build(holders, dev=creator)
    clusters = []
    by_wallet = {h["wallet"]: h for h in holders}
    for root, members, reasons in cl.groups([h["wallet"] for h in holders]):
        if len(members) < 2:
            continue
        share = sum(by_wallet[m]["share"] for m in members)
        clusters.append({"wallets": members, "share": share, "reasons": reasons,
                         "impact": sell_impact(share * float_tokens, reserve)})
    clusters.sort(key=lambda c: -c["share"])

    return {
        "mint": mint, "curve": curve, "creator": creator, "dev": dev, "graduated": graduated,
        "supply": supply, "float": float_tokens, "reserve": reserve, "create_slot": create_slot,
        "curve_state": curve_state, "holders": holders, "clusters": clusters, "early_read": n_early,
        "early_buyers": len(first), "n_holders": n_holders,
        "creator_history": history(creator) if (history and creator) else None,
        "rpc_calls": rpc.calls - calls0, "secs": round(time.time() - t0, 1),
    }
