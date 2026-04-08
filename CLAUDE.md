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

# Seed contracts from Dhan Option Chain API
python seed_contracts.py --underlying NIFTY --atm-range 10

# Start server (with contracts)
python main.py --contracts contracts.json --port 8000

# Demo mode (no credentials needed — simulated NIFTY feed)
python main.py --demo
```

There are no tests in this project — use `--demo` mode to validate behavior.

## Architecture

**Data Flow:**

```
Dhan WebSocket Feed (binary protocol)
  → DhanFeedClient (dhan_feed.py)     # Parses binary packets, reconnects
  → FareEngine (fare_engine.py)        # Black-Scholes/CoC calculations, thread-safe state
  → FastAPI Server (server.py)         # REST API + WebSocket broadcast
  → dashboard.html                     # Live browser UI
```

**Key files:**
- `fare_engine.py` — Core math: Black-Scholes, Cost of Carry, IV via Newton-Raphson. Thread-safe via `threading.Lock()`. History stored in deques (max 1000 per contract).
- `dhan_feed.py` — Parses Dhan's binary WebSocket protocol (8-byte headers: response_code, msg_length, exchange_seg, security_id). Batches subscriptions in 100-instrument chunks. Auto-reconnects with exponential backoff.
- `server.py` — FastAPI app. Global singletons: `engine` (FareEngine), `feed_client`, `ws_clients`. Bridges async uvicorn loop with threaded feed via `call_soon_threadsafe`.
- `main.py` — CLI entrypoint. Loads `contracts.json`, registers snapshot callbacks, starts uvicorn.
- `config.py` — Dataclass settings loaded from `.env`. Key vars: `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `FEED_MODE` (TICKER/QUOTE/FULL).

## Key Concepts

**Signal logic:** `|mispricing_pct| < 1.0` → FAIR; `mispricing > 0` → OVERVALUED (short); `mispricing < 0` → UNDERVALUED (long).

**Contract types:** CE (call), PE (put), FUT (futures). Futures use Cost of Carry (`F = S * e^((r-d)*T)`), options use Black-Scholes with Newton-Raphson IV solver.

**ContractMeta** → registered at startup via `engine.register_contract()` and `feed_client.subscribe()`. Can also be added dynamically via `POST /api/contracts/add`.

**Demo mode** (`--demo`): Skips Dhan credentials, simulates sine-wave NIFTY prices with Gaussian noise, ticks every 0.5s.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/fare` | All FareResults sorted by signal strength |
| `GET /api/fare/signals?min_pct=1.0` | Only mispriced contracts |
| `GET /api/history/{security_id}?limit=100` | Historical results |
| `POST /api/contracts/add` | Dynamically register a contract |
| `WS /ws/fare` | Live JSON stream of FareResult updates |
| `GET /docs` | Swagger/OpenAPI UI |
