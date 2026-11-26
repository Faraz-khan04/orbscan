"""python -m orbscan collect | scan <mint> | report | status"""
import argparse
import asyncio
import json
import logging
import sys

from . import config, db


def setup_logging(console=True):
    hs = [logging.FileHandler(config.LOG_PATH, encoding="utf-8")]
    if console:
        hs.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=hs)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orbscan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cp = sub.add_parser("collect", help="run the live collector (Ctrl+C to stop)")
    cp.add_argument("--for", dest="seconds", type=int, help="stop after this many seconds (batch mode)")
    sp = sub.add_parser("scan", help="scan one token now")
    sp.add_argument("mint")
    sp.add_argument("--json", action="store_true")
    sub.add_parser("report", help="write report.md and outcomes.csv")
    sub.add_parser("status", help="counts so far")
    a = ap.parse_args(argv)

    if a.cmd == "collect":
        setup_logging()
        from .collector import Collector
        col = Collector()
        try:
            asyncio.run(col.run_for(a.seconds) if a.seconds else col.run())
        except KeyboardInterrupt:
            pass
        finally:
            col.close()
    elif a.cmd == "scan":
        from .rpc import RPC
        from .scan import scan
        from .score import verdict
        import os
        hist = None
        if os.path.exists(config.DB_PATH):
            c = db.connect(config.DB_PATH)
            hist = lambda cr: db.creator_history(c, cr, a.mint)
        s = scan(RPC(), a.mint, history=hist)
        v = verdict(s)
        if a.json:
            print(json.dumps({"scan": s, "verdict": v}, default=str, indent=1))
            return
        m = v["metrics"]
        print(f"{a.mint}\n{v['verdict']}  score {v['score']}/100   ({s['secs']}s, {s['rpc_calls']} RPC calls)")
        print(f"{s['n_holders']} holders in total; top {m['holders']} read (unread {m['unread']}) · graduated {s['graduated']} · dev {s['dev']}")
        for k in ("cluster_share", "cluster_impact", "fresh_share", "transfer_share", "sniper_share", "top10_share", "dev_share"):
            print(f"  {k:15s} {m[k]:6.1%}   penalty {v['parts'].get(k, 0)}")
        print("  creator history:", s["creator_history"])
        for cl in s["clusters"][:5]:
            print(f"  cluster {len(cl['wallets'])} wallets {cl['share']:.1%} of float, sell impact {cl['impact']:.0%}: {', '.join(cl['reasons'])}")
        for f in v["flags"]:
            print("  FLAG:", f)
        for f in v["caps"]:
            print("  note:", f)
    elif a.cmd == "report":
        from .report import write
        print(write(db.connect(config.DB_PATH)))
    elif a.cmd == "status":
        c = db.connect(config.DB_PATH)
        q = lambda s: c.execute(s).fetchone()[0]
        print({"launches": q("SELECT COUNT(*) FROM launches"), "scanned": q("SELECT COUNT(*) FROM scans WHERE error IS NULL"),
               "scan_errors": q("SELECT COUNT(*) FROM scans WHERE error IS NOT NULL"), "tracked": q("SELECT COUNT(*) FROM tracked"),
               "snaps": q("SELECT COUNT(*) FROM snaps"),
               "verdicts": dict(c.execute("SELECT verdict, COUNT(*) FROM scans WHERE error IS NULL GROUP BY verdict").fetchall())})


if __name__ == "__main__":
    main()
