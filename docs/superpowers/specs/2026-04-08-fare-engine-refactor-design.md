# Fare Engine Refactor — Design Spec
**Date:** 2026-04-08

## Overview

Refactor the F&O fair value engine to:
- Replace custom binary Dhan WebSocket parser with the official Dhan Python SDK
- Auto-resolve all contract metadata from Dhan's scrip master CSV (user provides only symbol + expiry + strike + type)
- Remove simulation/demo mode and all contract preloading
- Restructure into `src/` package layout
- Add quant-level metrics (2nd/3rd order Greeks + market structure indicators)
- Add subscribe/unsubscribe API and dashboard controls
- Containerize with multistage Docker build
- Subscribe up to 15,000 instruments across 3 connections via a tiered ConnectionPool
- Fully interactive dashboard with fuzzy search, tabbed views, slot usage meter, cross-exchange tagging, and ATM rotation

---

## Capacity Planning

| Resource | Limit |
|----------|-------|
| Dhan max connections per user | 5 |
| Reserved for other services | 2 |
| **Available to this engine** | **3** |
| Instruments per connection | 5,000 |
| **Total instrument slots** | **15,000** |
| Instruments per subscription message | 100 |

**F&O universe (from scrip master):**

| Segment | Count |
|---------|-------|
| NSE F&O (NSE_FNO) | ~39,224 |
| MCX commodity F&O | ~28,154 |
| NSE Currency F&O | ~11,429 |
| **Total** | **~79,000** |

15,000 slots cover ~19% of all F&O instruments. Tier strategy covers the most tradeable zone.

---

## Project Structure

```
fare-value/
├── src/
│   ├── core/
│   │   ├── fare_engine.py        # Black-Scholes, CoC, all Greeks + quant metrics
│   │   └── models.py             # ContractMeta, Tick, FareResult dataclasses
│   ├── feed/
│   │   ├── dhan_feed.py          # Single MarketFeed wrapper (one connection)
│   │   └── connection_pool.py    # Owns 3 MarketFeed instances, slot accounting
│   ├── subscription/
│   │   ├── tier_config.py        # TierConfig dataclass + load/save to config file
│   │   ├── rotation_manager.py   # ATM rotation: spot-watch, batch unsubscribe+subscribe
│   │   └── slot_tracker.py       # Slot usage counts, capacity forecasting
│   ├── scrip/
│   │   └── scrip_master.py       # CSV download, in-memory cache, resolve(), daily refresh
│   ├── search/
│   │   └── fuzzy_index.py        # In-memory fuzzy index over scrip master (~79,000 rows)
│   ├── api/
│   │   ├── routes/
│   │   │   ├── contracts.py      # POST /add, DELETE /{id}, subscribe/unsubscribe
│   │   │   ├── fare.py           # GET /fare, /signals, /history
│   │   │   ├── scrip.py          # GET /api/scrip/expiries
│   │   │   ├── tiers.py          # GET/POST /api/tiers
│   │   │   ├── search.py         # GET /api/search?q=
│   │   │   └── health.py         # GET /health, /api/slots
│   │   └── schemas.py            # Pydantic request/response models
│   └── utils/
│       └── time_utils.py         # IST timezone helpers, expiry math
├── static/
│   └── dashboard.html
├── server.py                     # FastAPI app, lifespan, mounts routes
├── main.py                       # CLI entrypoint: --port, --host, --interval
├── config.py                     # Settings dataclass (.env)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

**Deleted:** `dhan_feed.py` (root), `seed_contracts.py`, `contracts.json`

---

## Component Responsibilities

### `src/scrip/scrip_master.py`
- Downloads `https://images.dhan.co/api-data/api-scrip-master.csv` at startup
- Persists to `cache/scrip_master.csv` (Docker volume); uses cached file if fresh (< 24h old)
- Builds in-memory lookup index: `(symbol, expiry, strike, type) → ContractMeta`
- Refreshes daily at **08:45 IST** via `threading.Timer`
- `resolve(symbol, expiry, strike, type) → ContractMeta` — auto-fills `security_id`, `underlying_security_id`, `underlying_symbol`, `exchange_segment`, `lot_size`
- `get_expiries(symbol) → list[date]` — for dashboard dropdown population
- Tags instruments listed on both NSE and BSE with `cross_listed: true` and `exchanges: ["NSE", "BSE"]`
- Raises `ContractNotFoundError` (→ HTTP 404) or `AmbiguousContractError` (→ HTTP 422) on bad input

### `src/search/fuzzy_index.py`
- Built at startup from scrip master DataFrame using `rapidfuzz` for fuzzy matching
- Index keys: `SYMBOL_NAME`, `DISPLAY_NAME`, `TRADING_SYMBOL`
- `search(query, limit=20) → list[ScripResult]` — returns scored matches with all metadata
- Unsubscribed results include `subscribed: false`, `slot_cost: N` (how many slots subscribing would consume — 1 for the contract + 1 for underlying if not already subscribed)
- Frontend debounces input at 300ms before calling `GET /api/search?q=`

### `src/feed/connection_pool.py`
- Owns exactly 3 `DhanFeedClient` instances (one per available Dhan connection)
- `subscribe(security_id, exchange_segment)` — assigns to least-loaded connection with capacity; batches in chunks of 100
- `unsubscribe(security_id, exchange_segment)` — removes from whichever connection holds it
- Delegates all tick callbacks to `FareEngine.on_tick()`
- Both the derivative contract AND its underlying index/stock are subscribed together (underlying counts against slot budget)

### `src/subscription/tier_config.py`
Three tiers, all configurable from the dashboard:

**Tier 1 — Index full chains (always-on)**
- Configured underlyings: e.g. `[NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX]`
- All strikes, all expiries for each underlying
- Estimated slots: ~800–1,200 per index × configured count

**Tier 2 — ATM-centric stocks**
- Configured stock list (e.g. top 50 F&O stocks)
- Per-underlying ATM range: `±N strikes` (default `±10`, configurable per underlying)
- Dynamic rotation as spot moves (handled by `RotationManager`)
- Configured expiries: nearest weekly + monthly, or all

**Tier 3 — Manual one-offs**
- Individual contracts added via dashboard search or `POST /api/contracts/add`
- No auto-rotation
- `TierConfig` persisted to `cache/tier_config.json` so it survives restarts

### `src/subscription/rotation_manager.py`
- Watches spot price ticks for all Tier 2 underlyings
- On each spot tick: computes new ATM, checks if any subscribed strikes are now outside `±N` range
- If rotation needed: batch-unsubscribes out-of-range strikes, batch-subscribes newly in-range strikes
- Unsubscribed strikes retain last `FareResult` in memory as stale (with `stale: true`, `stale_since` timestamp)
- Stale results evicted after configurable TTL (default 30 min)
- Rotation skipped if slot budget would be exceeded (logs warning, dashboard shows alert)

### `src/subscription/slot_tracker.py`
- Tracks: `used_slots`, `total_slots` (15,000), per-tier breakdown
- `forecast(new_contracts) → {slots_needed, slots_remaining_after}` — used by dashboard preview
- Exposed via `GET /api/slots`

### `src/core/fare_engine.py`
- Thread-safe state via `threading.Lock()`
- `register_contract(meta: ContractMeta)` / `deregister_contract(security_id)`
- `on_tick(security_id, tick)` → triggers `_calculate()` → returns `FareResult`
- Per-security IV history deque (252 entries, one slot per calendar day — intraday ticks update current day's slot in-place)
- Pairs CE+PE by `(underlying, expiry, strike)` for Put-Call Parity deviation and Skew
- Snapshot callbacks unchanged

### `server.py`
- Serves `static/dashboard.html` via `FileResponse` at `GET /`
- No simulation mode, no static file mount
- Global singletons: `engine`, `connection_pool`, `scrip_master`, `fuzzy_index`, `slot_tracker`, `rotation_manager`
- Lifespan: init scrip master → build fuzzy index → init connection pool → apply tier config → start rotation manager

### `main.py`
- Args: `--port` (default 8000), `--host` (default 0.0.0.0), `--interval` (default 30.0)
- No `--contracts`, no `--demo`
- Registers snapshot logging callback, starts uvicorn

---

## Scrip Master — Symbol Resolution

**User provides:** `symbol`, `expiry`, `strike`, `type` (CE/PE/FUT)

**System resolves:** `security_id`, `underlying_security_id`, `underlying_symbol`, `exchange_segment`, `lot_size`, `cross_listed`, `exchanges`

**Flow:**
```
POST /api/contracts/add {symbol, expiry, strike, type}
  → scrip_master.resolve(...)
  → ContractMeta (fully populated)
  → slot_tracker.forecast([meta]) → check capacity
  → engine.register_contract(meta)
  → connection_pool.subscribe(meta.security_id, meta.exchange_segment)
  → connection_pool.subscribe(meta.underlying_security_id, underlying_segment)
```

---

## Cross-Exchange Tagging

Instruments listed on both NSE and BSE (e.g. RELIANCE, TCS futures/options) are tagged at scrip master load time by matching on `ISIN` across segments.

- `ContractMeta` gains fields: `cross_listed: bool`, `exchanges: list[str]`, `peer_security_id: str | None`
- When subscribing a cross-listed instrument, the dashboard shows a prompt: "Also available on BSE — subscribe both to track spread?"
- If both legs subscribed: `FareResult` gains `exchange_spread: float` (NSE price − BSE price) as an arb signal
- Dashboard tags cross-listed rows with a `NSE|BSE` badge

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard HTML |
| GET | `/api/contracts` | List all tracked contracts |
| POST | `/api/contracts/add` | Add contract `{symbol, expiry, strike, type}` |
| POST | `/api/contracts/subscribe/{security_id}` | Re-subscribe a paused/stale contract |
| DELETE | `/api/contracts/unsubscribe/{security_id}` | Unsubscribe, keep stale history |
| DELETE | `/api/contracts/{security_id}` | Full remove (unsubscribe + clear state) |
| GET | `/api/scrip/expiries?symbol=NIFTY` | Available expiry dates for a symbol |
| GET | `/api/search?q=NIFTY&limit=20` | Fuzzy search across all ~79,000 scrip master instruments |
| GET | `/api/tiers` | Get current TierConfig |
| POST | `/api/tiers` | Update TierConfig (underlying list, ATM range, expiry filter) |
| GET | `/api/slots` | Slot usage: used, total, per-tier, stale count |
| GET | `/api/fare` | All FareResults sorted by signal strength |
| GET | `/api/fare/signals?min_pct=1.0` | Mispriced contracts only |
| GET | `/api/fare/{security_id}` | Single contract result |
| GET | `/api/history/{security_id}?limit=100` | Historical results |
| GET | `/api/health` | Status counts |
| WS | `/ws/fare` | Live FareResult JSON stream |
| GET | `/docs` | Swagger UI |

---

## Quant Metrics

### Enhanced Greeks (2nd/3rd order)

| Metric | Formula | Trading Use |
|--------|---------|-------------|
| Vanna | ∂Delta/∂σ = ∂Vega/∂S | Delta hedge adjustment when vol moves |
| Volga (Vomma) | ∂²V/∂σ² | Vol-of-vol exposure / vega convexity |
| Charm | ∂Delta/∂t | Delta decay per day — intraday hedge drift |
| Speed | ∂Gamma/∂S | Rate of gamma change with spot |
| Color | ∂Gamma/∂t | Gamma decay per day |
| Zomma | ∂Gamma/∂σ | Gamma sensitivity to vol — vol scalping signal |

### Market Structure Metrics

| Metric | Calculation | Trading Use |
|--------|------------|-------------|
| IV Rank | `(IV - 52w_low) / (52w_high - 52w_low) × 100` | Is current vol cheap or expensive historically |
| IV Percentile | `% of days IV < current IV (rolling 252d)` | More robust than IV Rank for skewed distributions |
| Moneyness | `ln(S/K) / (σ√T)` | Normalized distance from ATM |
| Intrinsic Value | `max(S-K, 0)` CE / `max(K-S, 0)` PE | Floor value, non-time component |
| Time Value | `Market Price - Intrinsic Value` | Premium attributable to time and vol |
| Put-Call Parity Deviation | `(C - P) - (S - K·e^(-rT))` | Arb signal between paired CE/PE at same strike |
| Basis | `Futures Market Price - S·e^((r-d)·T)` | Cash-futures mispricing / carry signal |
| Skew | `IV(OTM PE) - IV(OTM CE)` at same delta | Vol demand imbalance, tail risk pricing |
| Exchange Spread | `NSE price - BSE price` | Cross-exchange arb signal (cross-listed only) |

**IV History:** Per-security deque of 252 IV snapshots, sampled at most once per calendar day (last solved IV of the day). Intraday ticks update the current day's slot in-place. Used for IV Rank and IV Percentile.

**Put-Call Parity & Skew:** Engine maintains a `pairs` index by `(underlying, expiry, strike)`. When both legs are tracked and have live prices, parity deviation and skew are computed and written onto each FareResult.

---

## FareResult — Full Field Set

```json
{
  "security_id": "42528",
  "symbol": "NIFTY24APR23500CE",
  "contract_type": "CE",
  "strike": 23500,
  "expiry": "2025-04-24",
  "market_price": 145.5,
  "fair_value": 138.2,
  "mispricing": 7.3,
  "mispricing_pct": 5.28,
  "signal": "OVERVALUED",
  "signal_strength": 5.28,
  "underlying_price": 23512.0,
  "tte_years": 0.0438,
  "calculated_at": "2025-04-24T10:30:15",
  "delta": 0.54, "gamma": 0.0013, "theta": -15.2, "vega": 12.2,
  "implied_volatility": 13.45,
  "vanna": 0.023, "volga": 0.041, "charm": -0.003,
  "speed": 0.00012, "color": -0.0004, "zomma": 0.0018,
  "iv_rank": 62.4, "iv_percentile": 58.1,
  "moneyness": 0.142, "intrinsic_value": 0.0, "time_value": 145.5,
  "pc_parity_deviation": 1.2, "basis": -3.4, "skew": 2.1,
  "exchange_spread": 0.35,
  "cross_listed": true, "exchanges": ["NSE", "BSE"],
  "tier": 1,
  "stale": false, "stale_since": null
}
```

---

## Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│  F&O Fare Engine          [🔍 Search instruments...]         │
│  Slots: ████████░░░░░░ 9,240 / 15,000  [Tier Config ⚙]      │
├──────────────────────────────────────────────────────────────┤
│  [Signals] [By Underlying] [All Subscribed] [Search Results] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  SIGNALS TAB (default)                                       │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ OVERVALUED  (short candidates)  sorted by Mis% ▼     │    │
│  │ Symbol      Strike  Mkt   Fair  Mis%  IV   IVR  [×]  │    │
│  │ NIFTY CE    23500   145   138   +5.3  13.4  62  [×]  │    │
│  ├──────────────────────────────────────────────────────┤    │
│  │ UNDERVALUED (long candidates)   sorted by Mis% ▼     │    │
│  │ Symbol      Strike  Mkt   Fair  Mis%  IV   IVR  [×]  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  BY UNDERLYING TAB                                           │
│  [Underlying ▾: NIFTY]  [Expiry ▾: 24-Apr]                  │
│  Sortable table with all subscribed strikes for selected     │
│  underlying. Stale rows shown greyed with timestamp.         │
│                                                              │
│  ALL SUBSCRIBED TAB                                          │
│  Virtual-scrolled table (handles 15,000 rows).              │
│  Columns configurable. NSE|BSE badge on cross-listed rows.   │
│                                                              │
│  SEARCH RESULTS TAB                                          │
│  Populated when user types in search bar (debounced 300ms).  │
│  Unsubscribed rows show [+ Subscribe] with slot cost preview │
│  e.g. "+ Subscribe (uses 2 slots, 5,761 remaining)"          │
│  Cross-listed instruments show "Also on BSE" prompt.         │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  TIER CONFIG PANEL (slide-in from right, ⚙ button)          │
│  Tier 1 — Index full chains                                  │
│    [x] NIFTY  [x] BANKNIFTY  [x] FINNIFTY  [ ] MIDCPNIFTY  │
│    Estimated slots: 4,200  ████░░░░░░                        │
│  Tier 2 — ATM-centric stocks                                 │
│    Stocks: [RELIANCE, TCS, INFY, ...]  [Edit list]           │
│    ATM range: ± [10] strikes   Expiries: [Nearest 2 ▾]       │
│    Estimated slots: 3,800  ███░░░░░░░                        │
│  Tier 3 — Manual (from search)                               │
│    12 contracts  Slots: 240  ░░░░░░░░░░                      │
│  ─────────────────────────────────────                       │
│  Total: 8,240 / 15,000  ████████░░  [Apply Changes]          │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  METRICS LEGEND (collapsible)                                │
│  ┌─────────────────┬────────────────────────────────────┐    │
│  │ Metric          │ Formula + Trading Use               │    │
│  ├─────────────────┼────────────────────────────────────┤    │
│  │ Delta           │ ∂V/∂S — directional exposure        │    │
│  │ Gamma           │ ∂²V/∂S² — convexity                │    │
│  │ Theta           │ ∂V/∂t — daily time decay            │    │
│  │ Vega            │ ∂V/∂σ — vol sensitivity             │    │
│  │ Vanna           │ ∂Δ/∂σ — hedge drift on vol move    │    │
│  │ Volga           │ ∂²V/∂σ² — vega convexity           │    │
│  │ Charm           │ ∂Δ/∂t — intraday delta drift        │    │
│  │ Speed           │ ∂Γ/∂S — gamma acceleration          │    │
│  │ Color           │ ∂Γ/∂t — gamma time decay            │    │
│  │ Zomma           │ ∂Γ/∂σ — gamma/vol sensitivity      │    │
│  │ IV Rank         │ (IV-low)/(high-low)×100             │    │
│  │ IV Percentile   │ % days IV below current             │    │
│  │ Moneyness       │ ln(S/K)/(σ√T)                       │    │
│  │ Intrinsic Value │ max(S-K,0) / max(K-S,0)             │    │
│  │ Time Value      │ Price - Intrinsic                   │    │
│  │ PC Parity Dev   │ (C-P) - (S-Ke^{-rT})               │    │
│  │ Basis           │ F - S·e^{(r-d)T}                    │    │
│  │ Skew            │ IV(OTM PE) - IV(OTM CE)             │    │
│  │ Exchange Spread │ NSE price - BSE price (arb signal)  │    │
│  └─────────────────┴────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## Docker

**Dockerfile (multistage):**
- Stage 1 (`builder`): `python:3.12-slim` — install build deps (gcc etc.), `pip install --no-cache-dir` to `/install`
- Stage 2 (`runtime`): `python:3.12-slim` — copy only `/install`, copy `src/`, `static/`, `server.py`, `main.py`, `config.py`. Non-root `appuser`. `EXPOSE 8000`. `CMD ["python", "main.py"]`

**docker-compose.yml:**
- Single service `fare-engine`
- `env_file: .env` for `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`
- `restart: unless-stopped`
- Named volume `scrip_cache:/app/cache` — persists scrip master CSV and tier_config.json across restarts

---

## Startup Sequence

```
main.py
  → uvicorn starts FastAPI lifespan
  → scrip_master.load() — download or use cached CSV, build lookup index
  → fuzzy_index.build() — index all ~79,000 rows for search
  → connection_pool.init() — create 3 MarketFeed instances, start threads
  → tier_config.load() — read cache/tier_config.json (or defaults)
  → rotation_manager.start() — subscribe Tier 1 + Tier 2 per config
  → tier_config.restore_tier3() — re-subscribe any manually added Tier 3 contracts saved in tier_config.json
  → server ready, dashboard available at /
```

---

## Removed

- `dhan_feed.py` (root) — replaced by `src/feed/dhan_feed.py` + `connection_pool.py`
- `seed_contracts.py` — scrip master replaces manual seeding
- `contracts.json` — no preloading
- `--contracts` and `--demo` CLI args
- `FEED_MODE` env var — always Full mode
- Simulation / demo mode entirely
