# Architecture

## System Overview

```mermaid
graph TB
    DhanWS["Dhan WebSocket API"]
    DhanDepthWS["Dhan Depth WebSocket API<br/>wss://depth-api-feed.dhan.co/twentydepth"]
    DhanRestAPI["Dhan REST API<br/>Option Chain"]

    subgraph ConnectionPool["Connection Pool (3 connections x 5,000 slots)"]
        F1["DhanFeedClient #0"]
        F2["DhanFeedClient #1"]
        F3["DhanFeedClient #2"]
    end

    DhanWS -->|"ticks (Full mode)"| F1
    DhanWS -->|"ticks (Full mode)"| F2
    DhanWS -->|"ticks (Full mode)"| F3

    DepthFeed["DepthFeedClient<br/>20-level depth<br/>max 50 instruments<br/>auto-rotates 30s"]
    DhanDepthWS -->|"binary depth data"| DepthFeed

    Engine["FairEngine<br/>BS + CoC + Greeks<br/>Thread-safe, O(1) lookup"]
    F1 -->|Tick + Liquidity| Engine
    F2 -->|Tick + Liquidity| Engine
    F3 -->|Tick + Liquidity| Engine
    DepthFeed -->|"20-level depth"| Engine

    CrossValidator["CrossValidator<br/>Greeks/IV deviation<br/>OK/WARN/ALERT"]
    DhanRestAPI -->|"option chain"| CrossValidator
    Engine -->|"computed values"| CrossValidator

    subgraph API["FastAPI Server"]
        REST["REST API"]
        WS["WebSocket /ws/fair"]
        OCRouter["Option Chain Router"]
    end

    Engine -->|FairResult| REST
    Engine -->|"run_coroutine_threadsafe"| WS
    CrossValidator -->|"deviation report"| OCRouter

    Dashboard["Dashboard<br/>static/dashboard.html"]
    WS -->|"JSON stream"| Dashboard

    ScripMaster["Scrip Master<br/>~225k instruments<br/>Thread-safe index swap"]
    ScripMaster -->|resolve| Engine
    ScripMaster -->|search| API

    MarketHours["MarketHours<br/>NSE 9:15-15:30 IST<br/>holiday calendar"]
    MarketHours -->|"sleep after close"| DepthFeed
    MarketHours -->|"sleep after close"| F1
```

## Data Flow

```mermaid
sequenceDiagram
    participant Dhan as Dhan WebSocket
    participant Feed as DhanFeedClient (per-thread event loop)
    participant Pool as ConnectionPool (thread-safe)
    participant Engine as FairEngine (thread-safe)
    participant API as FastAPI
    participant UI as Dashboard

    Dhan->>Feed: Binary tick (Full mode, includes liquidity fields)
    Feed->>Pool: on_tick callback
    Pool->>Engine: Tick(security_id, ltp, oi, volume, bid, ask, buy_qty, sell_qty)
    Engine->>Engine: O(1) reverse index lookup
    Engine->>Engine: Solve IV (Newton-Raphson)
    Engine->>Engine: Black-Scholes + Enhanced Greeks
    Engine->>Engine: Market Structure Metrics
    Engine->>Engine: Liquidity Score (volume, OI, spread_pct, bid/ask depth)
    Engine->>Engine: Clamp mispricing +/-500%
    Engine->>API: FairResult (with liquidity + depth fields) via run_coroutine_threadsafe
    API->>UI: WebSocket JSON push (asyncio.Lock protected)

    Note over Engine: DepthFeedClient (separate thread) pushes<br/>20-level depth bids/asks into Engine concurrently
```

## Thread Model

```mermaid
graph TB
    subgraph MainThread["Main Thread (asyncio event loop)"]
        Uvicorn["uvicorn"]
        FastAPI["FastAPI routes"]
        WsBroadcast["WS broadcast"]
    end

    subgraph FeedThread0["Feed Thread #0 (own event loop)"]
        DF0["DhanFeed.run_forever()"]
    end

    subgraph FeedThread1["Feed Thread #1 (own event loop)"]
        DF1["DhanFeed.run_forever()"]
    end

    subgraph FeedThread2["Feed Thread #2 (own event loop)"]
        DF2["DhanFeed.run_forever()"]
    end

    subgraph DepthThread["Depth Thread (own event loop)"]
        DD0["DepthFeedClient.run_forever()<br/>binary parser, 50 instruments<br/>auto-rotate every 30s"]
    end

    subgraph TimerThread["Timer Thread"]
        Refresh["ScripMaster daily refresh"]
        Snapshot["Snapshot callbacks"]
        DepthRotate["Depth rotation (top 50 signals)"]
    end

    subgraph MarketHoursThread["Market Hours Thread"]
        MH["MarketHours.wait_for_open()<br/>NSE holiday calendar<br/>graceful sleep after close"]
    end

    DF0 -->|"on_tick (threading.Lock)"| Engine["FairEngine"]
    DF1 -->|"on_tick (threading.Lock)"| Engine
    DF2 -->|"on_tick (threading.Lock)"| Engine
    DD0 -->|"on_depth (threading.Lock)"| Engine
    Engine -->|"run_coroutine_threadsafe"| WsBroadcast
```

## Package Structure

```mermaid
graph LR
    subgraph src
        main["main.py"]
        server["server.py"]
        config["config.py"]

        subgraph core
            models["models.py"]
            fair_engine["fair_engine.py"]
            cross_validator["cross_validator.py"]
        end

        subgraph feed
            dhan_feed["dhan_feed.py"]
            connection_pool["connection_pool.py"]
            depth_feed["depth_feed.py"]
        end

        subgraph subscription
            slot_tracker["slot_tracker.py"]
            tier_config["tier_config.py"]
            rotation_mgr["rotation_manager.py"]
        end

        subgraph scrip
            scrip_master["scrip_master.py"]
        end

        subgraph search
            fuzzy_index["fuzzy_index.py"]
        end

        subgraph utils
            market_hours["market_hours.py"]
        end

        subgraph api
            schemas["schemas.py"]
            subgraph routes
                fair_rt["fair.py"]
                contracts_rt["contracts.py"]
                scrip_rt["scrip.py"]
                search_rt["search.py"]
                tiers_rt["tiers.py"]
                health_rt["health.py"]
                optionchain_rt["optionchain.py"]
            end
        end
    end

    server --> core
    server --> feed
    server --> subscription
    server --> scrip
    server --> search
    server --> api
    main --> server
```

## Component Responsibilities

### Core

| Module | Responsibility |
|--------|---------------|
| `models.py` | Data classes: `ContractType`, `ContractMeta`, `Tick`, `FairResult`. IST timestamps. Idempotent `__post_init__`. |
| `fair_engine.py` | Black-Scholes pricing, Cost of Carry, IV solver, enhanced Greeks (vanna, volga, charm, speed, color, zomma), market metrics (IV rank, moneyness, put-call parity, basis, skew). Liquidity fields (volume, OI, bid, ask, spread, spread_pct, buy_qty, sell_qty, liquidity_score, low_liquidity). 20-level depth fields (depth_bids, depth_asks, total_bid_depth, total_ask_depth, bid_ask_imbalance). Thread-safe engine with O(1) reverse index for underlying lookup. Snapshot callbacks. Mispricing clamped +/-500%. Expired contracts skipped. |
| `cross_validator.py` | Compares engine-computed Greeks/IV against Dhan option chain API values. Produces deviation reports with OK/WARN/ALERT status per field. Tracks dhan_iv, dhan_delta, dhan_theta, dhan_gamma, dhan_vega, iv_deviation. |

### Feed

| Module | Responsibility |
|--------|---------------|
| `dhan_feed.py` | Wraps one `dhanhq.DhanFeed` SDK connection. Per-thread event loop (cleaned up on disconnect). Thread-safe subscribe/unsubscribe returning bool. Auto-reconnect with 5s delay. Sleeps gracefully when market is closed. |
| `connection_pool.py` | Manages 3 feed connections. Thread-safe least-loaded assignment. Checks subscribe return value. Propagates `max_instruments` config. |
| `depth_feed.py` | 20-level depth WebSocket client (`wss://depth-api-feed.dhan.co/twentydepth`). Max 50 instruments per connection. Binary frame parser. Auto-rotates every 30s to track top 50 signal contracts by mispricing strength. Per-thread event loop, sleeps gracefully when market closes. |

### Subscription

| Module | Responsibility |
|--------|---------------|
| `slot_tracker.py` | Thread-safe slot tracking with atomic reads (single lock in `forecast`/`to_dict`). `contains()` public method. Per-tier breakdown. |
| `tier_config.py` | Thread-safe JSON config. Atomic file writes (temp + rename). `update()` for batch mutations. Separate `tier1_expiry_count` and `tier2_expiry_count`. |
| `rotation_manager.py` | Subscribes underlyings automatically in tier1/tier2. Tier 1 protected from rotation/stale eviction. ATM rotation for Tier 2 using public engine/scrip_master methods. |

### Scrip & Search

| Module | Responsibility |
|--------|---------------|
| `scrip_master.py` | Downloads Dhan scrip master CSV. Thread-safe index rebuild (build into locals, swap under lock). Explicit `FUTURES_INST_TYPES` set. Strike rounding to 2dp. NaN guards. NSE-preferred underlying map. Cross-listing via ISIN. Daily refresh at 08:45 IST. Atomic downloads. |
| `fuzzy_index.py` | In-memory fuzzy search using `rapidfuzz`. |

### Utils

| Module | Responsibility |
|--------|---------------|
| `market_hours.py` | NSE trading hours (9:15–15:30 IST). Holiday calendar fetched from NSE API, cached to disk. Provides `is_market_open()`, `wait_for_open()`, and `time_to_next_session()` helpers. Feeds and depth client call `wait_for_open()` on reconnect so they sleep gracefully outside market hours rather than reconnect-looping. |

### API Routes

| Module | Responsibility |
|--------|---------------|
| `fair.py` | Fair value results, signals, single contract, history. All routes guarded with 503 if engine not initialized. |
| `contracts.py` | Register, subscribe, unsubscribe, deregister contracts. |
| `scrip.py` | Expiries and strikes lookup from scrip master. |
| `search.py` | Fuzzy search over F&O instruments. |
| `tiers.py` | Get/update tier configuration. |
| `health.py` | Health check and slot usage. |
| `optionchain.py` | Proxies Dhan option chain REST API, attaches engine-computed values (fair price, Greeks, IV) side-by-side. Exposes cross-validation deviation report via CrossValidator. |

## Pricing Models

### Options -- Black-Scholes

```mermaid
graph LR
    S["Spot Price S"] --> BS["Black-Scholes"]
    K["Strike K"] --> BS
    T["Time to Expiry T"] --> BS
    r["Risk-Free Rate r"] --> BS
    sigma["Volatility sigma"] --> BS
    BS --> Price["Theoretical Price"]
    BS --> Greeks["Greeks: delta, gamma, theta, vega"]
    BS --> Enhanced["Enhanced: vanna, volga,<br/>charm, speed, color, zomma"]
```

**Formulas:**
- `d1 = [ln(S/K) + (r + sigma^2/2)*T] / (sigma * sqrt(T))`
- `d2 = d1 - sigma * sqrt(T)`
- Call: `S*N(d1) - K*e^(-rT)*N(d2)`
- Put: `K*e^(-rT)*N(-d2) - S*N(-d1)`
- IV solved via Newton-Raphson (100 iterations, tol=1e-6)
- Degenerate inputs (S<=0, K<=0, T<=0, sigma<=0) return None

### Futures -- Cost of Carry

`F = S * e^((r - d) * T)` where `d` = dividend yield (default 0)

### Signal Logic

```mermaid
graph TD
    MIS["|mispricing_pct|"]
    MIS -->|"< 1%"| FAIR["FAIR -- no action"]
    MIS -->|">= 1%, positive"| OVER["OVERVALUED -- SHORT candidate"]
    MIS -->|">= 1%, negative"| UNDER["UNDERVALUED -- LONG candidate"]
```

Mispricing % clamped to +/-500%. Options with fair value < 1.0 get mispricing_pct = 0 (avoids spurious signals on near-worthless options).

## Capacity Planning

| Resource | Value |
|----------|-------|
| Dhan max connections/user | 5 |
| Reserved for other services | 1 |
| Available to this engine | 4 |
| Market data connections (#0–#2) | 3 x 5,000 = 15,000 instruments |
| Depth connection (#0) | 1 x 50 instruments (20-level) |
| **Total market data slots** | **15,000** |
| **Total depth slots** | **50** |
| F&O universe (scrip master) | ~225,000 |

**Connection budget:**

| Connection | Type | Capacity |
|------------|------|----------|
| Feed #0 | Market data (Full mode) | 5,000 instruments |
| Feed #1 | Market data (Full mode) | 5,000 instruments |
| Feed #2 | Market data (Full mode) | 5,000 instruments |
| Depth #0 | 20-level depth | 50 instruments (auto-rotated) |
| **Total** | | **4 of 5 Dhan connections** |

## Startup Sequence

```mermaid
sequenceDiagram
    participant Main as main.py
    participant Server as server.py (lifespan)
    participant Scrip as ScripMaster
    participant Fuzzy as FuzzyIndex
    participant MH as MarketHours
    participant Pool as ConnectionPool
    participant Depth as DepthFeedClient
    participant Rotation as RotationManager

    Main->>Server: uvicorn.run(app)
    Server->>Server: Capture event loop reference
    Server->>Server: Register fair_callback
    Server->>MH: load holiday calendar (NSE API, cached to disk)
    Server->>Scrip: load() -- download or use cached CSV
    Note over Scrip: Thread-safe: build locals, swap under lock
    Server->>Fuzzy: build() -- index F&O instruments
    Server->>Pool: init 3 DhanFeedClient instances
    Server->>Depth: init DepthFeedClient (50 instrument slots)
    Server->>Rotation: apply_tier1() -- subscribe index chains + underlyings
    Server->>Rotation: apply_tier2() -- subscribe ATM stocks + underlyings
    Server->>Rotation: restore_tier3() -- re-subscribe manual one-offs
    Server->>Pool: start() -- begin receiving ticks
    Server->>Depth: start() -- begin receiving 20-level depth (waits for market open)
    Server-->>Main: ready at http://localhost:8000
    Note over Pool,Depth: After market close (15:30 IST) feeds call<br/>MarketHours.wait_for_open() on next reconnect
```

## Thread Safety Summary

| Component | Protection | Pattern |
|-----------|-----------|---------|
| FairEngine | `threading.Lock` | Lock on all state mutations and reads |
| ScripMaster | `threading.Lock` | Build into locals, atomic swap under lock |
| DhanFeedClient | `threading.Lock` | Protects `_subscribed` and `_feed` |
| DepthFeedClient | `threading.Lock` | Protects subscription set and connection state |
| ConnectionPool | `threading.Lock` | Protects `_assignment` |
| SlotTracker | `threading.Lock` | Single-lock atomic reads in forecast/to_dict |
| TierConfig | `threading.Lock` | Batch `update()`, atomic file write |
| CrossValidator | stateless | Called per-request; reads engine state under engine lock |
| ws_clients | `asyncio.Lock` | Set with discard, snapshot before broadcast |
| fair_callback | `run_coroutine_threadsafe` | Thread-safe async dispatch |
