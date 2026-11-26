"""Pure functions that read a jsonParsed transaction. Kept apart so they can be tested offline."""


def account_keys(tx):
    keys = tx["transaction"]["message"]["accountKeys"]
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


def fee_payer(tx):
    return account_keys(tx)[0]


def sol_deltas(tx):
    """{address: lamport change} for every account in the transaction."""
    keys, m = account_keys(tx), tx["meta"]
    return {k: post - pre for k, pre, post in zip(keys, m["preBalances"], m["postBalances"])}


def token_deltas(tx, mint):
    """{owner: whole-token change} for one mint."""
    m, d = tx["meta"], {}
    for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for b in m.get(side) or []:
            if b.get("mint") != mint or not b.get("owner"):
                continue
            amt = float(b["uiTokenAmount"].get("uiAmount") or 0)
            d[b["owner"]] = d.get(b["owner"], 0.0) + sign * amt
    return {k: v for k, v in d.items() if abs(v) > 1e-9}


def programs(tx):
    """Every program id the transaction invoked, inner instructions included."""
    out = set()
    msg, meta = tx["transaction"]["message"], tx.get("meta") or {}
    for ix in msg.get("instructions", []):
        out.add(ix.get("programId"))
    for inner in meta.get("innerInstructions") or []:
        for ix in inner.get("instructions", []):
            out.add(ix.get("programId"))
    out.discard(None)
    return out


def funder_of(tx, wallet):
    """Who sent SOL to `wallet` in this transaction: the other account that lost the most lamports."""
    d = sol_deltas(tx)
    if d.get(wallet, 0) <= 0:
        return None
    others = [(v, k) for k, v in d.items() if k != wallet and v < 0]
    return min(others)[1] if others else None


def how_acquired(tx, wallet, mint, program_owned=frozenset()):
    """'buy' if the wallet paid SOL for the tokens, else ('transfer', sender)."""
    td = token_deltas(tx, mint)
    if td.get(wallet, 0) <= 0:
        return "unknown", None
    fee = tx["meta"].get("fee", 0)
    spent = -sol_deltas(tx).get(wallet, 0) - (fee if fee_payer(tx) == wallet else 0)
    senders = [(v, k) for k, v in td.items() if v < 0 and k != wallet]
    sender = min(senders)[1] if senders else None
    if spent > 2_500_000 or (sender in program_owned):   # paid > 0.0025 SOL beyond the fee, or tokens came from a pool/curve
        return "buy", sender
    if sender:
        return "transfer", sender
    return "unknown", None
