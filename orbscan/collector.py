"""The live loop: hear every launch, scan the ones that get traction, price everything we track for 24h."""
import asyncio
import logging
import random
import time
import traceback

from . import config, db
from .feed import launches
from .pump import bonding_curve, decode_curve
from .prices import prices
from .rpc import RPC
from .scan import scan
from .score import verdict

log = logging.getLogger("collector")


def keep_awake(on):
    """Windows: ask the OS not to sleep while the collector runs (released automatically when the process ends).
    Closing the lid can still sleep a laptop, depending on its power settings."""
    if not config.KEEP_AWAKE:
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
        log.info("keep-awake %s", "on" if on else "off")
    except Exception:
        pass


class Collector:
    def __init__(self):
        self.c = db.connect(config.DB_PATH)
        self.rpc = RPC()
        self.queue = asyncio.Queue(maxsize=config.QUEUE_MAX)
        self.stop = asyncio.Event()
        self.n = {"launches": 0, "triggered": 0, "scanned": 0, "scan_errors": 0, "dropped": 0, "snaps": 0}

    def on_launch(self, ev):
        ev["curve"] = ev.get("curve") or bonding_curve(ev["mint"])
        db.add_launch(self.c, ev, random.random() < config.BASELINE_RATE)
        self.n["launches"] += 1

    async def watch(self):
        """Every WATCH_EVERY s: read the curves of launches still inside their watch window; trigger a scan at TRIGGER_SOL."""
        while not self.stop.is_set():
            await asyncio.sleep(config.WATCH_EVERY)
            now = time.time()
            self.c.execute("UPDATE launches SET status='expired' WHERE status='watch' AND created_ts < ?", (now - config.WATCH_MINUTES * 60,))
            rows = self.c.execute("SELECT mint, curve FROM launches WHERE status='watch'").fetchall()
            if not rows:
                continue
            try:
                accs = await asyncio.to_thread(self.rpc.multiple_accounts, [r["curve"] for r in rows])
            except Exception as e:
                log.warning("watch sweep failed: %s", e)
                continue
            for r, acc in zip(rows, accs):
                cs = decode_curve(acc["data"]) if acc else None
                if cs and (cs["real_sol"] >= config.TRIGGER_SOL or cs["complete"]):
                    status = "queued"
                    try:
                        self.queue.put_nowait((r["mint"], r["curve"]))
                        self.n["triggered"] += 1
                    except asyncio.QueueFull:
                        status = "dropped"
                        self.n["dropped"] += 1
                    self.c.execute("UPDATE launches SET status=?, trigger_ts=? WHERE mint=?", (status, now, r["mint"]))
            self.c.commit()

    async def scanner(self):
        while not self.stop.is_set():
            mint, curve = await self.queue.get()
            creator = (self.c.execute("SELECT creator FROM launches WHERE mint=?", (mint,)).fetchone() or [None])[0]
            t0 = time.time()
            try:
                hist = db.creator_history(self.c, creator, mint) if creator else None
                s = await asyncio.to_thread(scan, self.rpc, mint, curve, creator, (lambda _c: hist))
                v = verdict(s)
                # entry = the price AFTER the scan finished: the earliest moment a user of the scanner could act
                px = await asyncio.to_thread(prices, self.rpc, [(mint, curve)])
                entry = px.get(mint, (None, 0))[0]
                mcap = entry * s["supply"] if entry else None
                detail = {"clusters": s["clusters"], "creator_history": s["creator_history"], "rpc_calls": s["rpc_calls"], "n_holders": s["n_holders"],
                          "holders": [{k: h.get(k) for k in ("wallet", "share", "fresh", "funder", "acquired", "sniper", "is_dev", "n_tx", "unread")} for h in s["holders"]]}
                secs = time.time() - t0
                if secs > config.MAX_SCAN_SECS:      # the PC slept or the RPC stalled: the entry price is stale
                    v["caps"].append("scan interrupted; not tracked")
                db.save_scan(self.c, mint, v, entry, mcap, secs, detail=detail)
                if entry and secs <= config.MAX_SCAN_SECS:
                    db.track(self.c, mint, "scan", entry)
                self.c.execute("UPDATE launches SET status='scanned' WHERE mint=?", (mint,))
                self.c.commit()
                self.n["scanned"] += 1
                log.info("scan %s %s score=%s %s %.0fs %d calls %s", mint[:8], v["verdict"], v["score"],
                         f"mcap={mcap:.0f} SOL" if mcap else "", time.time() - t0, s["rpc_calls"], "; ".join(v["flags"])[:160])
            except Exception as e:
                self.n["scan_errors"] += 1
                db.save_scan(self.c, mint, None, None, None, time.time() - t0, error=str(e)[:300])
                self.c.execute("UPDATE launches SET status='error' WHERE mint=?", (mint,))
                self.c.commit()
                log.warning("scan %s failed: %s", mint[:8], e)
                log.debug(traceback.format_exc())

    async def price_loop(self):
        while not self.stop.is_set():
            await asyncio.sleep(config.PRICE_EVERY)
            since = time.time() - config.TRACK_HOURS * 3600 - 600
            rows = self.c.execute("""SELECT DISTINCT t.mint, l.curve FROM tracked t JOIN launches l ON l.mint=t.mint
                                     WHERE t.start_ts > ?""", (since,)).fetchall()
            if not rows:
                continue
            try:
                px = await asyncio.to_thread(prices, self.rpc, [(r["mint"], r["curve"]) for r in rows])
            except Exception as e:
                log.warning("price sweep failed: %s", e)
                continue
            now = time.time()
            self.c.executemany("INSERT INTO snaps VALUES(?,?,?,?)", [(m, now, p, g) for m, (p, g) in px.items()])
            self.c.commit()
            self.n["snaps"] += len(px)

    async def heartbeat(self):
        while not self.stop.is_set():
            await asyncio.sleep(300)
            log.info("status %s queue=%d rpc_calls=%d", self.n, self.queue.qsize(), self.rpc.calls)

    def requeue(self):
        """A batch run may end with scans still queued: pick the fresh ones up again, drop the stale ones."""
        now = time.time()
        for r in self.c.execute("SELECT mint, curve, trigger_ts FROM launches WHERE status='queued'").fetchall():
            if r["trigger_ts"] and now - r["trigger_ts"] < 900:
                try:
                    self.queue.put_nowait((r["mint"], r["curve"]))
                    continue
                except asyncio.QueueFull:
                    pass
            self.c.execute("UPDATE launches SET status='dropped' WHERE mint=?", (r["mint"],))
        self.c.commit()

    def close(self):
        self.c.commit()
        self.c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.c.close()

    async def run_for(self, seconds):
        """Batch mode (GitHub Actions): run for a fixed time, then stop cleanly so the database can be saved."""
        try:
            await asyncio.wait_for(self.run(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        log.info("batch done %s rpc_calls=%d", self.n, self.rpc.calls)

    async def run(self):
        keep_awake(True)
        self.requeue()
        log.info("collector starting: rpc=%s trigger=%.1f SOL baseline=%.0f%%", config.RPC_URLS, config.TRIGGER_SOL, config.BASELINE_RATE * 100)
        await asyncio.gather(launches(self.on_launch, self.stop), self.watch(), self.scanner(), self.price_loop(), self.heartbeat())
