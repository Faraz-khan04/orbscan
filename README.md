# orbscan

A pump.fun launch scanner and a **paper** test of whether its verdicts predict anything.
Read-only: it never holds a key, signs, or sends a transaction.

Built to test a viral claim ("our scanner's alerts went 24x, 58x, 50x") the honest way: log **every**
token the scanner flags, not the three best, and see what happened after the moment you could have bought.

## How it works

1. **Feed** – every new pump.fun launch from PumpPortal's free websocket.
2. **Trigger** – a launch is scanned once its bonding curve holds `TRIGGER_SOL` (default 5 SOL) within 30 min.
3. **Scan** (~100 read-only RPC calls)
   - top 20 holders, with the curve, pools and burn address left out (share = share of the real float)
   - each wallet: fresh or experienced, who funded it, did it **buy** or was it **sent** the tokens
   - the token's first 25 transactions: who the dev is, who bought in the launch slot (snipers / bundles)
   - creator history from pump.fun's public API: serial launchers
4. **Link** wallets into groups (union-find): funded by another holder or the dev, tokens sent by one,
   fresh wallets sharing one funder, fresh wallets buying in the same slot.
5. **Score** 0–100 (`orbscan/score.py`), six straight-line penalties, plus red flags that force DANGER.
   Sell impact uses constant-product math: `price_after/price_before = (R/(R+Q))²`.
6. **Track** – entry price = price when the scan finished. Every 2 min for 24 h we record the price
   (curve before graduation, DexScreener after). A random 3% of *all* launches is tracked from launch as the control group.
7. **Report** – per verdict: how many peaked 2x/5x/10x, median return at 1 h and 24 h, how many died,
   and two paper strategies after 4% round-trip costs: hold 24 h, or take profit at 2x.

## Run on GitHub (no laptop needed)

`.github/workflows/collect.yml` runs the collector every 15 minutes for ~11 minutes on GitHub's machines and
saves the database and **report.md** to the `data` branch. Open `report.md` on the `data` branch to see the result.
Launches that arrive between runs are simply not sampled; that thins the sample but does not bias it.
Optional: add a free Helius RPC URL as the repository secret `ORB_RPC_URL` for faster, more reliable scans.

## Run locally

```
pip install websockets
python -m orbscan collect          # leave running (start.bat runs it hidden in the background)
python -m orbscan collect --for 600   # batch mode: stop after 10 minutes
python -m orbscan status
python -m orbscan report           # writes report.md and outcomes.csv
python -m orbscan scan <mint>      # one token, now
python -m unittest discover -s tests
```

Settings live in `orbscan/config.py`; override with env vars, e.g. `ORB_RPC_URL` (a free Helius key is
much faster than the public RPC), `ORB_TRIGGER_SOL`, `ORB_RPS`.

## Known limits

- Peaks are sampled every 2 min, so they understate spikes; nobody sells exactly at a peak anyway.
- The public RPC is slow and rate-limited; under heavy launch traffic some triggered tokens are dropped (counted in the log).
- Wallet linking is evidence-based and incomplete: CEX-funded or carefully separated wallets won't link.
- A few dozen tokens per verdict is noise. Let it run several days before reading anything into the numbers.

Nothing here is financial advice.
