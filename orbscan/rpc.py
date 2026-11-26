"""A small Solana JSON-RPC client (read-only methods only) that spreads calls over several endpoints."""
import itertools
import threading

from . import config
from .net import RateLimiter, http_json

PRIMARY_ONLY = {"getProgramAccounts", "getTokenLargestAccounts"}


class RPCError(Exception):
    pass


class RPC:
    def __init__(self, urls=None, rps=None):
        self.urls = list(urls or config.RPC_URLS)
        self.limiters = {u: RateLimiter(rps or config.RPS) for u in self.urls}
        self.ids = itertools.count(1)
        self.rr = itertools.cycle(self.urls)
        self.lock = threading.Lock()
        self.calls = 0

    def call(self, method, params=None):
        self.calls += 1
        if method in PRIMARY_ONLY:
            order = [self.urls[0]]
        else:
            with self.lock:
                first = next(self.rr)
            order = [first] + [u for u in self.urls if u != first]
        last = None
        for url in order:
            try:
                r = http_json(url, {"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params or []},
                              limiter=self.limiters[url], tries=3)
            except Exception as e:          # this endpoint is down or throttling: try the next one
                last = e
                continue
            if "error" in r:
                last = RPCError(f"{method}: {r['error']}")
                continue
            return r.get("result")
        raise last or RPCError(method)

    # helpers -----------------------------------------------------------
    def multiple_accounts(self, keys, encoding="base64", data_slice=None):
        out = []
        for i in range(0, len(keys), 100):
            opts = {"encoding": encoding, "commitment": "confirmed"}
            if data_slice:
                opts["dataSlice"] = data_slice
            out += self.call("getMultipleAccounts", [keys[i:i + 100], opts])["value"]
        return out

    def signatures(self, address, limit=100, before=None):
        opts = {"limit": limit, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        return self.call("getSignaturesForAddress", [address, opts]) or []

    def transaction(self, sig):
        return self.call("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
                                                  "commitment": "confirmed"}])

    def token_accounts(self, mint):
        """Every token account of a mint: [(address, owner, whole tokens)]. Works for Token and Token-2022."""
        prog = self.call("getAccountInfo", [mint, {"encoding": "base64"}])["value"]["owner"]
        filters = [{"memcmp": {"offset": 0, "bytes": mint}}]
        if prog == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
            filters.insert(0, {"dataSize": 165})
        res = self.call("getProgramAccounts", [prog, {"encoding": "jsonParsed", "filters": filters, "commitment": "confirmed"}])
        out = []
        for a in res or []:
            info = a["account"]["data"]["parsed"]["info"]
            out.append((a["pubkey"], info["owner"], float(info["tokenAmount"].get("uiAmount") or 0)))
        return out
