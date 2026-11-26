import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS launches(
  mint TEXT PRIMARY KEY, curve TEXT, creator TEXT, name TEXT, symbol TEXT,
  created_ts REAL, launch_price REAL, baseline INTEGER DEFAULT 0, status TEXT DEFAULT 'watch', trigger_ts REAL);
CREATE TABLE IF NOT EXISTS scans(
  mint TEXT PRIMARY KEY, ts REAL, score INTEGER, verdict TEXT, flags TEXT, metrics TEXT,
  entry_price REAL, entry_mcap REAL, secs REAL, error TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS tracked(
  mint TEXT, kind TEXT, start_ts REAL, entry_price REAL, PRIMARY KEY(mint, kind));
CREATE TABLE IF NOT EXISTS snaps(mint TEXT, ts REAL, price REAL, graduated INTEGER);
CREATE INDEX IF NOT EXISTS snaps_mint ON snaps(mint, ts);
CREATE INDEX IF NOT EXISTS launches_status ON launches(status, created_ts);
"""


def connect(path):
    c = sqlite3.connect(path, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def add_launch(c, ev, baseline):
    c.execute("INSERT OR IGNORE INTO launches(mint,curve,creator,name,symbol,created_ts,launch_price,baseline) VALUES(?,?,?,?,?,?,?,?)",
              (ev["mint"], ev.get("curve"), ev.get("creator"), ev.get("name"), ev.get("symbol"), time.time(), ev.get("price"), int(baseline)))
    if baseline and ev.get("price"):
        track(c, ev["mint"], "baseline", ev["price"])
    c.commit()


def track(c, mint, kind, price):
    c.execute("INSERT OR IGNORE INTO tracked VALUES(?,?,?,?)", (mint, kind, time.time(), price))
    c.execute("INSERT INTO snaps VALUES(?,?,?,0)", (mint, time.time(), price))
    c.commit()


def save_scan(c, mint, v, entry_price, entry_mcap, secs, error=None, detail=None):
    c.execute("INSERT OR REPLACE INTO scans VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (mint, time.time(), v and v["score"], v and v["verdict"], json.dumps(v and v["flags"]),
               json.dumps(v and v["metrics"]), entry_price, entry_mcap, secs, error, json.dumps(detail, default=str) if detail else None))
    c.commit()


def creator_history(c, creator, exclude_mint=None):
    """What our own record knows about a creator: earlier launches, and how many reached the scan trigger."""
    r = c.execute("""SELECT COUNT(*), SUM(CASE WHEN status NOT IN ('watch','expired') THEN 1 ELSE 0 END)
                     FROM launches WHERE creator=? AND mint<>?""", (creator, exclude_mint or "")).fetchone()
    return {"launched": r[0] or 0, "graduated": r[1] or 0, "source": "local"}
