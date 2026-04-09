# Usage Guide

## Prerequisites

- Python 3.12+
- Dhan trading account with API access

## Quick Start

```bash
# Clone
git clone <repo-url> && cd fair-value-engine

# Install
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env:
#   DHAN_CLIENT_ID=your_client_id
#   DHAN_ACCESS_TOKEN=your_access_token

# Run
python -m src.main
```

Open `http://localhost:8000` for the dashboard, `http://localhost:8000/docs` for Swagger UI.

## CLI Options

```bash
python -m src.main --port 8000 --host 0.0.0.0 --interval 30
```

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8000 | HTTP server port |
| `--host` | 0.0.0.0 | Bind address |
| `--interval` | 30.0 | Snapshot log interval in seconds |

## Docker

```bash
# Build and run
docker compose up --build

# Or standalone
docker build -t fair-engine .
docker run --env-file .env -p 8000:8000 fair-engine
```

The Docker setup uses a named volume `scrip_cache` to persist the scrip master CSV and tier config across restarts.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DHAN_CLIENT_ID` | Yes | -- | Dhan API client ID |
| `DHAN_ACCESS_TOKEN` | Yes | -- | Dhan API access token |
| `HOST` | No | 0.0.0.0 | Server bind address |
| `PORT` | No | 8000 | Server port |
| `LOG_LEVEL` | No | INFO | Python logging level |
| `MAX_CONNECTIONS` | No | 3 | Number of WebSocket feed connections |
| `INSTRUMENTS_PER_CONNECTION` | No | 5000 | Max instruments per connection |
| `SCRIP_CACHE_DIR` | No | cache | Directory for scrip master CSV cache |
| `STALE_TTL_MINUTES` | No | 30 | Minutes before stale data is evicted |

## What Happens on Startup

1. **Scrip master** downloads from Dhan (~225k instruments, cached for 24h, thread-safe index build)
2. **Fuzzy index** built over all F&O instruments for search
3. **3 WebSocket connections** opened (15,000 instrument slots total)
4. **Tier 1** subscribes index full chains (NIFTY, BANKNIFTY, etc.) + their underlyings automatically
5. **Tier 2/3** applied from saved config (if any)
6. **Ticks start flowing**, fair values calculated in real-time

If Dhan credentials are missing, server starts in degraded mode (no feed, API returns 503 for feed-dependent routes).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard UI |
| GET | `/api/fair` | All FairResults sorted by signal strength |
| GET | `/api/fair/signals?min_pct=1.0` | Only mispriced contracts |
| GET | `/api/fair/{security_id}` | Single contract result |
| GET | `/api/history/{security_id}?limit=100` | Historical results |
| GET | `/api/contracts` | List registered contracts |
| POST | `/api/contracts/add` | Add contract `{symbol, expiry, strike, contract_type}` |
| POST | `/api/contracts/subscribe/{id}` | Re-subscribe a paused contract |
| DELETE | `/api/contracts/unsubscribe/{id}` | Unsubscribe, keep stale data |
| DELETE | `/api/contracts/{id}` | Full remove (unsubscribe + deregister) |
| GET | `/api/scrip/expiries?symbol=NIFTY` | Available expiry dates |
| GET | `/api/scrip/strikes?symbol=NIFTY&expiry=2026-04-24` | Strikes for an expiry |
| GET | `/api/search?q=NIFTY&limit=20` | Fuzzy search instruments |
| GET | `/api/tiers` | Current tier configuration |
| POST | `/api/tiers` | Update tier configuration |
| GET | `/api/health` | Health check |
| GET | `/api/slots` | Slot usage breakdown |
| WS | `/ws/fair` | Live FairResult JSON stream |

## Dashboard Tabs

- **Signals** -- overvalued (short) and undervalued (long) candidates, sorted by mispricing %
- **By Underlying** -- drill into a specific underlying + expiry, see full option chain
- **All Subscribed** -- every active instrument with tier badges and cross-exchange tags
- **Search Results** -- fuzzy search across all F&O instruments, subscribe with one click

## Tier System

The engine manages subscriptions across 3 WebSocket connections (15,000 instrument slots total):

- **Tier 1** -- Index full chains (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX). All strikes, nearest N expiries. Underlyings auto-subscribed. Protected from rotation and stale eviction.
- **Tier 2** -- ATM-centric stocks. Nearest N strikes around ATM, auto-rotates as spot moves. Underlyings auto-subscribed. Out-of-range strikes marked stale with configurable TTL.
- **Tier 3** -- Manual one-offs. Individual contracts added via dashboard search or `POST /api/contracts/add`. Persisted across restarts.

Configure tiers via the dashboard's Tier Config panel or `POST /api/tiers`.

## API Examples

```bash
# Get all mispriced contracts (>2% mispricing)
curl http://localhost:8000/api/fair/signals?min_pct=2.0

# Add a specific contract
curl -X POST http://localhost:8000/api/contracts/add \
  -H "Content-Type: application/json" \
  -d '{"symbol": "NIFTY", "expiry": "2026-04-24", "strike": 23500, "contract_type": "CE"}'

# Search instruments
curl "http://localhost:8000/api/search?q=RELIANCE&limit=10"

# Check slot usage
curl http://localhost:8000/api/slots

# Get tier config
curl http://localhost:8000/api/tiers

# Update tiers
curl -X POST http://localhost:8000/api/tiers \
  -H "Content-Type: application/json" \
  -d '{"tier2_stocks": ["RELIANCE", "TCS", "INFY"], "tier2_atm_range": 10}'
```

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
# 91 tests covering: math, scrip resolution, feed clients, connection pool,
# slot tracking, tier config, rotation, API routes, models, time utils
```
