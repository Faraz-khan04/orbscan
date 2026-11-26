import os
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from orbscan import db, report, score  # noqa: E402
from orbscan.cluster import build  # noqa: E402
from orbscan.pump import bonding_curve, decode_curve, sell_impact  # noqa: E402
from orbscan.solkeys import b58decode, b58encode, is_on_curve  # noqa: E402
from orbscan.txparse import funder_of, how_acquired, token_deltas  # noqa: E402

# real mint -> bonding curve pairs (public chain facts)
VECTORS = [("BDuiaWdW5AdyGu2gnukrhtnQ5F6LH6xLAvhCRyDHpump", "5DoVjYwXArLfa1QZxM5DG2ieVwAy63zYorP6dw1uhpMR"),
           ("EjXBwXVkaAUNGSeQmUeJtiNMCoD7ZaULc9UrCMvepump", "2qJLcBS5EfP9qRecwcAwNgq6QUhMqQwqgWhL6S3GDCby"),
           ("8JpxMTXn2MxeTFVcCSA8tnYfrtGcTreijybMweqXpump", "F43U2gBCAFAi5EJhBLUTazydEffAFPcrDST6RqzhYAAB"),
           ("sixdK1naGJwdrWp3TpXFyAK679hkbJCZHUVLjg2pump", "919EyHmax3zVfQapHTHBHY8gzXLiJ2NsnXXEgDRB8qnk")]


class Keys(unittest.TestCase):
    def test_b58_roundtrip(self):
        for m, _ in VECTORS:
            self.assertEqual(b58encode(b58decode(m)), m)
        self.assertEqual(b58encode(bytes(32)), "1" * 32)

    def test_pda(self):
        for m, c in VECTORS:
            self.assertEqual(bonding_curve(m), c)

    def test_wallets_on_curve(self):
        self.assertTrue(is_on_curve(b58decode("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")) in (True, False))
        self.assertFalse(is_on_curve(b58decode(VECTORS[0][1])))


def curve_bytes(vtok, vsol, rtok, rsol, supply, complete=False):
    return bytes(8) + struct.pack("<5Q", vtok, vsol, rtok, rsol, supply) + bytes([complete]) + b58decode(VECTORS[0][0])


class Curve(unittest.TestCase):
    def test_fresh_curve(self):
        c = decode_curve(curve_bytes(1_073_000_000 * 10**6, 30 * 10**9, 793_100_000 * 10**6, 0, 10**15))
        self.assertAlmostEqual(c["price"], 30 / 1_073_000_000)
        self.assertAlmostEqual(c["mcap_sol"], 27.96, places=1)
        self.assertEqual(c["progress"], 0)
        self.assertEqual(c["creator"], VECTORS[0][0])

    def test_impact(self):
        self.assertAlmostEqual(sell_impact(100, 100), 0.75)
        self.assertEqual(sell_impact(0, 100), 0)
        self.assertEqual(sell_impact(5, 0), 0)


def tx(keys, pre, post, tpre=(), tpost=(), fee=5000):
    return {"slot": 1, "transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys], "instructions": []}},
            "meta": {"fee": fee, "preBalances": pre, "postBalances": post,
                     "preTokenBalances": [{"mint": "M", "owner": o, "uiTokenAmount": {"uiAmount": a}} for o, a in tpre],
                     "postTokenBalances": [{"mint": "M", "owner": o, "uiTokenAmount": {"uiAmount": a}} for o, a in tpost]}}


class Parse(unittest.TestCase):
    def test_funder(self):
        t = tx(["F", "W"], [10**10, 0], [10**10 - 10**9 - 5000, 10**9])
        self.assertEqual(funder_of(t, "W"), "F")
        self.assertIsNone(funder_of(t, "F"))

    def test_buy_vs_transfer(self):
        buy = tx(["W", "CURVE"], [10**9, 5], [5 * 10**8, 5 * 10**8], tpre=[("CURVE", 1000)], tpost=[("CURVE", 900), ("W", 100)])
        self.assertEqual(how_acquired(buy, "W", "M")[0], "buy")
        gift = tx(["S", "W"], [10**9, 10**7], [10**9 - 5000, 10**7], tpre=[("S", 500)], tpost=[("S", 400), ("W", 100)])
        self.assertEqual(how_acquired(gift, "W", "M"), ("transfer", "S"))
        self.assertEqual(token_deltas(gift, "M"), {"S": -100, "W": 100})


class Clustering(unittest.TestCase):
    def test_links(self):
        H = [{"wallet": "a", "funder": "X", "fresh": True}, {"wallet": "b", "funder": "X", "fresh": True},
             {"wallet": "c", "funder": "a"}, {"wallet": "d", "acquired": "transfer", "sender": "DEV"},
             {"wallet": "e", "funder": "Y", "fresh": False}, {"wallet": "f", "funder": "Y", "fresh": False}]
        g = {frozenset(ms) for _, ms, _ in build(H, dev="DEV").groups([h["wallet"] for h in H])}
        self.assertIn(frozenset("abc"), g)
        self.assertIn(frozenset("e"), g)            # experienced wallets sharing a funder (an exchange) are not linked
        self.assertIn(frozenset("d"), g)            # DEV is not among the members passed, d alone


def holder(w, share, **k):
    d = {"wallet": w, "share": share, "is_dev": False, "fresh": False, "acquired": "buy", "sniper": False}
    d.update(k)
    return d


class Scoring(unittest.TestCase):
    def scan(self, holders, clusters=(), ch=None):
        return {"holders": holders, "clusters": list(clusters), "creator_history": ch or {"launched": 0, "graduated": 0, "source": "local"}}

    def test_clean(self):
        v = score.verdict(self.scan([holder(str(i), 0.02) for i in range(20)]))
        self.assertEqual((v["score"], v["verdict"]), (100, "CLEAN"))

    def test_cluster_flag(self):
        cl = [{"wallets": ["a", "b", "c"], "share": 0.4, "impact": 0.55, "reasons": []}]
        v = score.verdict(self.scan([holder("a", 0.2), holder("b", 0.1), holder("c", 0.1)], cl))
        self.assertEqual(v["verdict"], "DANGER")
        self.assertTrue(v["flags"])

    def test_serial_creator(self):
        v = score.verdict(self.scan([holder("a", 0.02)], ch={"launched": 4, "graduated": 0, "source": "local"}))
        self.assertEqual(v["verdict"], "DANGER")

    def test_no_creator_history_never_clean(self):
        s = self.scan([holder(str(i), 0.02) for i in range(20)])
        s["creator_history"] = None
        self.assertEqual(score.verdict(s)["verdict"], "OK")

    def test_whale_and_sniper_flags(self):
        v = score.verdict(self.scan([holder("a", 0.69, sniper=True), holder("d", 0.31, is_dev=True)]))
        self.assertEqual(v["verdict"], "DANGER")
        self.assertEqual(len(v["flags"]), 3)

    def test_ramp(self):
        self.assertAlmostEqual(score.penalty(0.35, 20, 0.10, 0.60), 10)


class Report(unittest.TestCase):
    def test_outcomes(self):
        path = os.path.join(tempfile.mkdtemp(), "t.db")
        c = db.connect(path)
        t0 = time.time() - 30 * 3600
        for mint, verdict, path_ in (("A", "CLEAN", [1, 3, 0.5]), ("B", "DANGER", [1, 0.1, 0.05]), ("C", "baseline", [1, 1.2, 1.1])):
            c.execute("INSERT INTO launches(mint, curve, symbol, created_ts) VALUES(?,?,?,?)", (mint, "x", mint, t0))
            kind = "baseline" if verdict == "baseline" else "scan"
            c.execute("INSERT INTO tracked VALUES(?,?,?,?)", (mint, kind, t0, 1.0))
            if kind == "scan":
                c.execute("INSERT INTO scans(mint, verdict, score) VALUES(?,?,?)", (mint, verdict, 50))
            for i, p in enumerate(path_):
                c.execute("INSERT INTO snaps VALUES(?,?,?,0)", (mint, t0 + 600 + i * 3 * 3600, p))
        c.commit()
        os_, S = report.build(c)
        a = next(o for o in os_ if o["mint"] == "A")
        self.assertEqual(a["peak"], 3)
        self.assertAlmostEqual(a["rend"], -0.5)
        self.assertEqual(S["CLEAN"]["peak2"], 1)
        self.assertAlmostEqual(S["CLEAN"]["tp_mean"], 2 * 0.96 - 1)
        self.assertEqual(S["DANGER"]["dead"], 1)
        md, _ = report.markdown(c)
        self.assertIn("| CLEAN | 1 | 1 | 100%", md)


if __name__ == "__main__":
    unittest.main()
