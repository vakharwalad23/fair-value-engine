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
python main.py --port 8000
```

Run the test suite:

```bash
.venv/bin/python -m pytest tests/ -v
```

## Architecture

**Data Flow:**

```
Dhan SDK MarketFeed (WebSocket)
  → DhanFeedClient (src/feed/dhan_feed.py)          # SDK wrapper, tick callbacks
  → ConnectionPool (src/feed/connection_pool.py)     # Multi-connection slot management
  → FairEngine (src/core/fair_engine.py)             # Black-Scholes/CoC calculations, thread-safe state
  → FastAPI Server (server.py)                       # REST API + WebSocket broadcast
  → static/dashboard.html                            # Live browser UI
```

**Key files:**
- `src/core/fair_engine.py` — Core math: Black-Scholes, Cost of Carry, IV via Newton-Raphson. Thread-safe via `threading.Lock()`. History stored in deques (max 1000 per contract).
- `src/core/models.py` — Dataclasses: `ContractMeta`, `Tick`, `FairResult`, `ContractType` enum.
- `src/feed/dhan_feed.py` — Wraps Dhan SDK `MarketFeed`. Manages subscriptions, tick callbacks, reconnection.
- `src/feed/connection_pool.py` — Distributes instrument subscriptions across multiple feed connections (985 slots each).
- `src/scrip/scrip_master.py` — Loads Dhan scrip master CSV, resolves security IDs for options/futures by symbol, expiry, strike.
- `src/search/fuzzy_index.py` — In-memory fuzzy search over scrip names using rapidfuzz.
- `src/subscription/slot_tracker.py` — Tracks used/available slots per connection.
- `src/subscription/tier_config.py` — Persistent JSON config for tier-1/tier-2/tier-3 strike ranges.
- `src/subscription/rotation_manager.py` — Rotates ATM-window subscriptions as spot price moves.
- `src/api/routes/` — FastAPI routers: `fair.py`, `contracts.py`, `scrip.py`, `search.py`, `tiers.py`, `health.py`.
- `server.py` — FastAPI app. Global singletons: `engine`, `pool`, `scrip_master`, `fuzzy_index`, `tier_config`, `rotation_manager`. WebSocket broadcast via `call_soon_threadsafe`.
- `main.py` — CLI entrypoint. Initialises components and starts uvicorn.
- `config.py` — Dataclass settings loaded from `.env`. Key vars: `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `FEED_MODE` (TICKER/QUOTE/FULL).

## Key Concepts

**Signal logic:** `|mispricing_pct| < 1.0` → FAIR; `mispricing > 0` → OVERVALUED (short); `mispricing < 0` → UNDERVALUED (long).

**Contract types:** CE (call), PE (put), FUT (futures). Futures use Cost of Carry (`F = S * e^((r-d)*T)`), options use Black-Scholes with Newton-Raphson IV solver.

**ContractMeta** → registered at startup via `engine.register_contract()` and `pool.subscribe()`. Can also be added dynamically via `POST /api/contracts/add`.

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
| `GET /api/scrip/expiries?underlying=NIFTY` | List expiries for an underlying |
| `GET /api/scrip/strikes?underlying=NIFTY&expiry=...` | List strikes for expiry |
| `GET /api/search?q=NIFTY&limit=20` | Fuzzy search scrip names |
| `GET /api/tiers` | Get tier configuration |
| `POST /api/tiers` | Update tier configuration |
| `GET /api/health` | Health check |
| `GET /api/slots` | Slot usage per connection |
| `WS /ws/fair` | Live JSON stream of FairResult updates |
| `GET /docs` | Swagger/OpenAPI UI |
