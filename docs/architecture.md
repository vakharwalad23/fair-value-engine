# Architecture

## System Overview

```mermaid
graph TB
    DhanWS["Dhan WebSocket API"]

    subgraph ConnectionPool["Connection Pool (3 connections)"]
        F1["DhanFeedClient #0"]
        F2["DhanFeedClient #1"]
        F3["DhanFeedClient #2"]
    end

    DhanWS -->|"ticks (Full mode)"| F1
    DhanWS -->|"ticks (Full mode)"| F2
    DhanWS -->|"ticks (Full mode)"| F3

    Engine["FairEngine<br/>BS + CoC + Greeks"]
    F1 -->|Tick| Engine
    F2 -->|Tick| Engine
    F3 -->|Tick| Engine

    subgraph API["FastAPI Server"]
        REST["REST API"]
        WS["WebSocket /ws/fair"]
    end

    Engine -->|FairResult| REST
    Engine -->|FairResult| WS

    Dashboard["Dashboard<br/>static/dashboard.html"]
    WS -->|"JSON stream"| Dashboard

    ScripMaster["Scrip Master<br/>~79,000 instruments"]
    ScripMaster -->|resolve| Engine
    ScripMaster -->|search| API
```

## Data Flow

```mermaid
sequenceDiagram
    participant Dhan as Dhan WebSocket
    participant Pool as ConnectionPool
    participant Engine as FairEngine
    participant API as FastAPI
    participant UI as Dashboard

    Dhan->>Pool: Binary tick (Full mode)
    Pool->>Engine: Tick(security_id, ltp, oi, volume)
    Engine->>Engine: Solve IV (Newton-Raphson)
    Engine->>Engine: Black-Scholes + Enhanced Greeks
    Engine->>Engine: Market Structure Metrics
    Engine->>API: FairResult callback
    API->>UI: WebSocket JSON push
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
        end

        subgraph feed
            dhan_feed["dhan_feed.py"]
            connection_pool["connection_pool.py"]
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

        subgraph api
            schemas["schemas.py"]
            subgraph routes
                fair_rt["fair.py"]
                contracts_rt["contracts.py"]
                scrip_rt["scrip.py"]
                search_rt["search.py"]
                tiers_rt["tiers.py"]
                health_rt["health.py"]
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
| `models.py` | Data classes: `ContractType`, `ContractMeta`, `Tick`, `FairResult` |
| `fair_engine.py` | Black-Scholes pricing, Cost of Carry, IV solver, enhanced Greeks (vanna, volga, charm, speed, color, zomma), market metrics (IV rank, moneyness, put-call parity, basis, skew), thread-safe engine with pair index |

### Feed

| Module | Responsibility |
|--------|---------------|
| `dhan_feed.py` | Wraps one `dhanhq.MarketFeed` SDK connection. Converts tick callbacks to `Tick` objects. |
| `connection_pool.py` | Manages 3 feed connections. Routes subscribe/unsubscribe to least-loaded connection. |

### Subscription

| Module | Responsibility |
|--------|---------------|
| `slot_tracker.py` | Tracks used/available instrument slots per tier. Capacity forecasting. |
| `tier_config.py` | Persists tier settings (index chains, ATM stocks, manual one-offs) to JSON. |
| `rotation_manager.py` | Watches spot prices. Rotates Tier 2 subscriptions to keep ATM window active. Marks out-of-range strikes as stale with TTL eviction. |

### Scrip & Search

| Module | Responsibility |
|--------|---------------|
| `scrip_master.py` | Downloads Dhan scrip master CSV, caches locally, builds lookup index. Resolves `(symbol, expiry, strike, type)` to full `ContractMeta`. Detects cross-listed instruments via ISIN. Daily refresh at 08:45 IST. |
| `fuzzy_index.py` | In-memory fuzzy search over ~79,000 instruments using `rapidfuzz`. |

## Pricing Models

### Options — Black-Scholes

```mermaid
graph LR
    S["Spot Price S"] --> BS["Black-Scholes"]
    K["Strike K"] --> BS
    T["Time to Expiry T"] --> BS
    r["Risk-Free Rate r"] --> BS
    sigma["Volatility σ"] --> BS
    BS --> Price["Theoretical Price"]
    BS --> Greeks["Greeks: Δ Γ θ ν"]
    BS --> Enhanced["Enhanced: vanna, volga,<br/>charm, speed, color, zomma"]
```

**Formulas:**
- `d1 = [ln(S/K) + (r + sigma^2/2)*T] / (sigma * sqrt(T))`
- `d2 = d1 - sigma * sqrt(T)`
- Call: `S*N(d1) - K*e^(-rT)*N(d2)`
- Put: `K*e^(-rT)*N(-d2) - S*N(-d1)`
- IV solved via Newton-Raphson (100 iterations, tol=1e-6)

### Futures — Cost of Carry

`F = S * e^((r - d) * T)` where `d` = dividend yield (default 0)

### Signal Logic

```mermaid
graph TD
    MIS["|mispricing_pct|"]
    MIS -->|"< 1%"| FAIR["FAIR — no action"]
    MIS -->|">= 1%, positive"| OVER["OVERVALUED — SHORT candidate"]
    MIS -->|">= 1%, negative"| UNDER["UNDERVALUED — LONG candidate"]
```

## Capacity Planning

| Resource | Value |
|----------|-------|
| Dhan max connections/user | 5 |
| Reserved for other services | 2 |
| Available to this engine | 3 |
| Instruments per connection | 5,000 |
| **Total slots** | **15,000** |
| F&O universe (scrip master) | ~79,000 |
| Coverage | ~19% |

## Startup Sequence

```mermaid
sequenceDiagram
    participant Main as main.py
    participant Server as server.py (lifespan)
    participant Scrip as ScripMaster
    participant Fuzzy as FuzzyIndex
    participant Pool as ConnectionPool
    participant Rotation as RotationManager

    Main->>Server: uvicorn.run(app)
    Server->>Scrip: load() — download or use cached CSV
    Server->>Fuzzy: build() — index ~79k instruments
    Server->>Pool: init 3 MarketFeed connections
    Server->>Rotation: apply_tier1() — subscribe index chains
    Server->>Rotation: apply_tier2() — subscribe ATM stocks
    Server->>Rotation: restore_tier3() — re-subscribe manual one-offs
    Server->>Pool: start() — begin receiving ticks
    Server-->>Main: ready at http://localhost:8000
```
