"""All settings in one place. Override any of them with an environment variable of the same name (ORB_ prefix)."""
import os


def _env(name, default, cast=str):
    v = os.environ.get("ORB_" + name)
    return default if v is None or v == "" else cast(v)


# Calls rotate across these. The first one also serves getProgramAccounts (the holder list), which most free
# endpoints refuse. A free Helius/QuickNode URL in ORB_RPC_URL goes first and makes scans much faster.
RPC_URLS = [u for u in [_env("RPC_URL", ""), "https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"] if u]
RPC_URL = RPC_URLS[0]
RPS = _env("RPS", 3.0, float)                     # requests per second, per endpoint
FEED_URL = _env("FEED_URL", "wss://pumpportal.fun/api/data")
DEX_URL = "https://api.dexscreener.com/tokens/v1/solana/"

DB_PATH = _env("DB", "orbscan.db")
LOG_PATH = _env("LOG", "orbscan.log")

TRIGGER_SOL = _env("TRIGGER_SOL", 5.0, float)     # scan a launch once its curve holds this much real SOL
WATCH_MINUTES = _env("WATCH_MINUTES", 30, int)     # how long after launch we wait for it to hit the trigger
BASELINE_RATE = _env("BASELINE_RATE", 0.03, float) # share of ALL launches tracked from launch, unfiltered (the control group)
QUEUE_MAX = _env("QUEUE_MAX", 60, int)
TRACK_HOURS = _env("TRACK_HOURS", 24.0, float)
PRICE_EVERY = _env("PRICE_EVERY", 120, int)        # seconds between price sweeps
WATCH_EVERY = _env("WATCH_EVERY", 45, int)
MAX_SCAN_SECS = _env("MAX_SCAN_SECS", 600, int)    # a slower scan (PC asleep, RPC stalled) is not tracked
KEEP_AWAKE = _env("KEEP_AWAKE", 1, int)            # Windows: keep the PC from sleeping while collecting

# scan
TOP_N = 20
EARLY_TXS = 25            # oldest transactions of the mint read for first buyers
FRESH_MAX_TXS = 10        # a wallet with fewer signatures than this is fresh
FRESH_MAX_AGE_H = 48      # ...or whose whole history is younger than this

# paper trading
ROUND_TRIP_COST = _env("ROUND_TRIP_COST", 0.04, float)  # fees + slippage, buy and sell together
