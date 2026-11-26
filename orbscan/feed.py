"""New pump.fun launches from PumpPortal's free websocket."""
import asyncio
import json
import logging

import websockets

from . import config

log = logging.getLogger("feed")


def parse(msg):
    """PumpPortal create event -> our launch dict, or None."""
    try:
        d = json.loads(msg)
    except Exception:
        return None
    if d.get("txType") != "create" or not d.get("mint"):
        return None
    vsol, vtok = d.get("vSolInBondingCurve"), d.get("vTokensInBondingCurve")
    price = (vsol / vtok) if vsol and vtok else None
    return {"mint": d["mint"], "curve": d.get("bondingCurveKey"), "creator": d.get("traderPublicKey"),
            "name": (d.get("name") or "")[:60], "symbol": (d.get("symbol") or "")[:20], "price": price,
            "pool": d.get("pool")}


async def launches(on_launch, stop):
    delay = 2
    while not stop.is_set():
        try:
            async with websockets.connect(config.FEED_URL, ping_interval=20, ping_timeout=20, max_size=2 ** 20) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                log.info("feed connected")
                delay = 2
                async for msg in ws:
                    ev = parse(msg)
                    if ev and (ev.get("pool") in (None, "pump")):
                        on_launch(ev)
                    if stop.is_set():
                        break
        except Exception as e:
            log.warning("feed dropped: %s; reconnecting in %ss", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
