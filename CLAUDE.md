# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Real-time F&O (Futures & Options) fair value calculation engine for Indian markets via Dhan broker. Calculates theoretical prices using Black-Scholes and Cost of Carry models, detects mispricing signals, and serves them via REST/WebSocket APIs.

## Setup & Running

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env with credentials
# DHAN_CLIENT_ID=...
# DHAN_ACCESS_TOKEN=...

# Start server
python -m src.main --port 8000
```

Run the test suite:

```bash
.venv/bin/python -m pytest tests/ -v
```

## Architecture

**Data Flow:**

```
Dhan SDK DhanFeed (WebSocket, Full mode)
  -> DhanFeedClient (src/feed/dhan_feed.py)          # SDK wrapper, tick callbacks, per-thread event loop
  -> ConnectionPool (src/feed/connection_pool.py)     # 3 connections, thread-safe slot management
  -> FairEngine (src/core/fair_engine.py)             # BS/CoC calculations, thread-safe state, reverse index
  -> FastAPI Server (src/server.py)                   # REST API + WebSocket broadcast via run_coroutine_threadsafe
  -> static/dashboard.html                            # Live browser UI
```

**Key files:**
- `src/core/fair_engine.py` — Black-Scholes with enhanced Greeks (vanna, volga, charm, speed, color, zomma), Cost of Carry, Newton-Raphson IV solver. Thread-safe via `threading.Lock()`. O(1) underlying->contracts reverse index. IV history (252-day rolling, one per calendar day). Pair index for put-call parity. Mispricing clamped to +/-500%. Expired contracts skipped. Snapshot callbacks fired periodically.
- `src/core/models.py` — Dataclasses: `ContractMeta`, `Tick`, `FairResult`, `ContractType` enum. IST timestamps.
- `src/feed/dhan_feed.py` — Wraps Dhan SDK `DhanFeed`. Per-thread event loop. Thread-safe subscribe/unsubscribe. Auto-reconnect with 5s delay. Returns bool from subscribe().
- `src/feed/connection_pool.py` — Distributes instruments across 3 connections (5,000 slots each). Thread-safe via lock. Least-loaded assignment.
- `src/scrip/scrip_master.py` — Downloads Dhan scrip master CSV, caches locally. Thread-safe index rebuild (build into locals, swap under lock). Resolves (symbol, expiry, strike, type) to ContractMeta. Explicit futures type set (no OPTFUT misclassification). Strike rounding to 2dp. Cross-listing via ISIN. Daily refresh at 08:45 IST. Atomic file downloads.
- `src/search/fuzzy_index.py` — In-memory fuzzy search over scrip names using rapidfuzz.
- `src/subscription/slot_tracker.py` — Thread-safe slot tracking with atomic reads. `contains()` public method. Per-tier breakdown and capacity forecasting.
- `src/subscription/tier_config.py` — Thread-safe JSON config for tier-1/tier-2/tier-3. Atomic file writes. `update()` method for batch mutations.
- `src/subscription/rotation_manager.py` — Subscribes underlyings automatically in tier1/tier2. Tier 1 protected from rotation/stale eviction. ATM rotation for Tier 2 stocks.
- `src/api/routes/` — FastAPI routers: `fair.py`, `contracts.py`, `scrip.py`, `search.py`, `tiers.py`, `health.py`. All routes have None guards (503 if not initialized). Uses public engine/tracker methods.
- `src/server.py` — FastAPI app with lifespan. Async broadcast via `run_coroutine_threadsafe`. WebSocket client set with asyncio.Lock. Graceful degraded mode if scrip master fails.
- `src/main.py` — CLI entrypoint. Registers snapshot logger, starts uvicorn.
- `src/config.py` — Dataclass settings from `.env`. Key vars: `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `MAX_CONNECTIONS`, `INSTRUMENTS_PER_CONNECTION`, `SCRIP_CACHE_DIR`, `STALE_TTL_MINUTES`.

## Key Concepts

**Signal logic:** `|mispricing_pct| < 1.0` -> FAIR; `mispricing > 0` -> OVERVALUED (short); `mispricing < 0` -> UNDERVALUED (long). Clamped to +/-500%.

**Contract types:** CE (call), PE (put), FUT (futures). Futures use Cost of Carry (`F = S * e^((r-d)*T)`), options use Black-Scholes with Newton-Raphson IV solver.

**ContractMeta** -> registered via `engine.register_contract()` and `pool.subscribe()`. Can be added dynamically via `POST /api/contracts/add`. Underlying subscribed automatically.

**Thread safety:** All shared state protected by locks. Scrip master swaps indexes atomically. Feed client and pool use locks. Callbacks snapshot before iteration.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/fair` | All FairResults sorted by signal strength |
| `GET /api/fair/signals?min_pct=1.0` | Only mispriced contracts |
| `GET /api/fair/{security_id}` | Single contract fair result |
| `GET /api/history/{security_id}?limit=100` | Historical results |
| `GET /api/contracts` | List registered contracts |
| `POST /api/contracts/add` | Dynamically register a contract |
| `POST /api/contracts/subscribe/{security_id}` | Subscribe an existing contract to the feed |
| `DELETE /api/contracts/unsubscribe/{security_id}` | Unsubscribe from feed |
| `DELETE /api/contracts/{security_id}` | Deregister a contract |
| `GET /api/scrip/expiries?symbol=NIFTY` | List expiries for an underlying |
| `GET /api/scrip/strikes?symbol=NIFTY&expiry=...` | List strikes for expiry |
| `GET /api/search?q=NIFTY&limit=20` | Fuzzy search scrip names |
| `GET /api/tiers` | Get tier configuration |
| `POST /api/tiers` | Update tier configuration |
| `GET /api/health` | Health check |
| `GET /api/slots` | Slot usage per connection |
| `WS /ws/fair` | Live JSON stream of FairResult updates |
| `GET /docs` | Swagger/OpenAPI UI |
