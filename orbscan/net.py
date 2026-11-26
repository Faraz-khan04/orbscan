"""HTTP JSON with a shared rate limit, retries and backoff. Standard library only."""
import json
import random
import threading
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "orbscan/0.1 (+research, read-only)", "Content-Type": "application/json", "Accept": "application/json"}


class RateLimiter:
    def __init__(self, rps: float):
        self.gap = 1.0 / max(rps, 0.1)
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


def http_json(url, body=None, timeout=20, limiter=None, tries=5):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(tries):
        if limiter:
            limiter.wait()
        try:
            req = urllib.request.Request(url, data=data, headers=UA, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        time.sleep(min(20, (2 ** i) + random.random()))
    raise RuntimeError(f"request failed after {tries} tries: {last}")
