"""pump.fun specifics: program ids, the bonding-curve account and its price."""
import base64
import struct

from .solkeys import b58decode, b58encode, find_pda

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
SYSTEM = "11111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"
TOKEN_DECIMALS = 6
CURVE_TOKENS_FOR_SALE = 793_100_000        # real tokens on a fresh curve
STANDARD_VIRTUAL_SOL = 30.0
BURN = {"1nc1nerator11111111111111111111111111111111"}


def bonding_curve(mint: str) -> str:
    return find_pda([b"bonding-curve", b58decode(mint)], PUMP_PROGRAM)[0]


def decode_curve(raw) -> dict | None:
    """raw: bytes, or the [base64, 'base64'] pair an RPC returns."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = base64.b64decode(raw[0])
    if len(raw) < 49:
        return None
    vtok, vsol, rtok, rsol, supply = struct.unpack_from("<5Q", raw, 8)
    c = {
        "vtok": vtok, "vsol": vsol, "rtok": rtok, "rsol": rsol, "supply": supply,
        "complete": bool(raw[48]),
        "creator": b58encode(raw[49:81]) if len(raw) >= 81 else None,
    }
    # a standard pump.fun curve starts with 30 virtual SOL; anything else (custom/abnormal curves) has a meaningless price
    c["standard"] = abs((vsol - rsol) / 1e9 - STANDARD_VIRTUAL_SOL) < 1.0
    c["price"] = price_sol(vsol, vtok)
    c["mcap_sol"] = c["price"] * supply / 10 ** TOKEN_DECIMALS if c["price"] else 0.0
    c["real_sol"] = rsol / 1e9
    c["progress"] = max(0.0, min(1.0, 1 - (rtok / 10 ** TOKEN_DECIMALS) / CURVE_TOKENS_FOR_SALE))
    return c


def price_sol(vsol_lamports, vtok_raw) -> float:
    """SOL per whole token."""
    if not vtok_raw:
        return 0.0
    return (vsol_lamports / 1e9) / (vtok_raw / 10 ** TOKEN_DECIMALS)


def sell_impact(q: float, reserve: float) -> float:
    """Fraction the price falls when q tokens are sold into a constant-product pool holding `reserve` tokens.
    x*y=k: price ∝ y/x, after the sale x' = x+q, y' = k/x', so price'/price = (x/x')^2."""
    if q <= 0 or not reserve or reserve <= 0:
        return 0.0
    return 1 - (reserve / (reserve + q)) ** 2
