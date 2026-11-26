"""Union-find over wallets, keeping the reason two wallets were joined."""


class Clusters:
    def __init__(self):
        self.parent = {}
        self.reasons = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def link(self, a, b, reason):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra
            self.reasons.setdefault(ra, []).extend(self.reasons.pop(rb, []))
        self.reasons.setdefault(ra, []).append(reason)

    def groups(self, members):
        g = {}
        for m in members:
            g.setdefault(self.find(m), []).append(m)
        return [(root, ms, sorted(set(self.reasons.get(root, [])))) for root, ms in g.items()]


def build(holders, dev=None):
    """holders: list of dicts with wallet, funder, acquired, sender, early_slot, fresh.
    Returns Clusters. Links:
      strong  funded by another holder or the dev; tokens received from another holder or the dev
      pack    two fresh wallets funded by the same source
      bundle  two fresh wallets that bought in the same early slot"""
    c = Clusters()
    inside = {h["wallet"] for h in holders} | ({dev} if dev else set())
    by_funder, by_slot = {}, {}
    for h in holders:
        w = h["wallet"]
        c.find(w)
        f = h.get("funder")
        if f and f in inside and f != w:
            c.link(f, w, "funded by " + ("the dev" if f == dev else "another holder"))
        s = h.get("sender")
        if h.get("acquired") == "transfer" and s and s in inside and s != w:
            c.link(s, w, "tokens sent by " + ("the dev" if s == dev else "another holder"))
        if h.get("fresh") and f:
            by_funder.setdefault(f, []).append(w)
        if h.get("fresh") and h.get("early_slot") is not None:
            by_slot.setdefault(h["early_slot"], []).append(w)
    for f, ws in by_funder.items():
        for w in ws[1:]:
            c.link(ws[0], w, "fresh wallets with one funder")
    for s, ws in by_slot.items():
        for w in ws[1:]:
            c.link(ws[0], w, "fresh wallets buying in one slot")
    return c
