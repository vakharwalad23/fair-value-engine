# F&O Fare Engine

Real-time F&O fair value calculator using Dhan's live market feed.

## Architecture

```
Dhan WebSocket Feed
        │
        ▼
  DhanFeedClient           ← binary packet parser (dhan_feed.py)
        │  ticks
        ▼
   FareEngine              ← Black-Scholes / Cost-of-Carry (fare_engine.py)
        │  FareResult
        ├──► FastAPI REST  ← /api/fare, /api/signals etc (server.py)
        └──► WebSocket     ← /ws/fare  (live push to dashboard)
                │
                ▼
          Dashboard (dashboard.html)
```

## Fair Value Formulas

### Options (CE / PE) — Black-Scholes
```
d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
d2 = d1 - σ·√T

CE fair = S·N(d1) - K·e^(-rT)·N(d2)
PE fair = K·e^(-rT)·N(-d2) - S·N(-d1)

Implied Volatility → Newton-Raphson solver on market price
```

### Futures — Cost of Carry
```
F_fair = S · e^((r - d)·T)

S = spot price, r = risk-free rate (6.5%), d = dividend yield, T = years to expiry
```

### Mispricing
```
Mispricing ₹   = Market Price − Fair Value
Mispricing %   = Mispricing / Fair Value × 100

> +1%  → OVERVALUED  → SHORT candidate
< -1%  → UNDERVALUED → LONG candidate
```

## Setup

```bash
# 1. Clone / extract
cd fno_fare

# 2. Install deps
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env with your DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN

# 4. Seed contracts from Option Chain API (optional — fetches live)
python seed_contracts.py --underlying NIFTY --atm-range 10

# 5. Start server
python main.py

# Or with custom options:
python main.py --contracts contracts.json --port 8000 --interval 30

# Demo mode (no credentials needed — uses simulated data)
python main.py --demo
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard UI |
| GET | `/api/fare` | All FareResults sorted by signal strength |
| GET | `/api/fare/signals?min_pct=2.0` | Only over/undervalued contracts |
| GET | `/api/fare/{security_id}` | Single contract result |
| GET | `/api/history/{security_id}` | Historical results |
| GET | `/api/contracts` | List registered contracts |
| POST | `/api/contracts/add` | Add new contract dynamically |
| POST | `/api/intervals` | Set snapshot log interval |
| WS | `/ws/fare` | Live fare updates stream |
| GET | `/api/health` | Health check |
| GET | `/docs` | Swagger UI |

## FareResult Schema

```json
{
  "security_id": "42528",
  "symbol": "NIFTY2350023500CE",
  "type": "CE",
  "strike": 23500,
  "expiry": "2025-04-24",
  "market_price": 145.5,
  "fair_value": 138.2,
  "mispricing": 7.3,
  "mispricing_pct": 5.28,
  "signal": "OVERVALUED",
  "signal_strength": 5.28,
  "delta": 0.5387,
  "gamma": 0.00132,
  "theta": -15.15,
  "vega": 12.18,
  "iv": 13.45,
  "underlying_price": 23512.0,
  "tte_years": 0.0438,
  "calculated_at": "2025-04-24T10:30:15"
}
```

## Trading Logic

| Signal | Action | Why |
|--------|--------|-----|
| OVERVALUED (+) | SHORT | Option premium bloated vs BS theoretical |
| UNDERVALUED (-) | LONG | Option trading cheap vs BS fair value |
| FAIR | No action | Within 1% of theoretical price |

> **Note**: Mispricing % threshold (default 1%) is configurable. In liquid NIFTY options,
> spreads are typically <0.5%, so even 2% mispricing is meaningful.
> Always validate with market depth (bid/ask spread) before trading.

## Interval Snapshots

The engine prints a table of top signals to terminal every N seconds (default 30s).
You can change this via API:

```bash
curl -X POST http://localhost:8000/api/intervals \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds": 15}'
```

Or pass `--interval 15` at startup.
