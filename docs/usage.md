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
| `DHAN_CLIENT_ID` | Yes | — | Dhan API client ID |
| `DHAN_ACCESS_TOKEN` | Yes | — | Dhan API access token |
| `HOST` | No | 0.0.0.0 | Server bind address |
| `PORT` | No | 8000 | Server port |
| `LOG_LEVEL` | No | INFO | Python logging level |
| `MAX_CONNECTIONS` | No | 3 | Number of WebSocket feed connections |
| `INSTRUMENTS_PER_CONNECTION` | No | 5000 | Max instruments per connection |
| `SCRIP_CACHE_DIR` | No | cache | Directory for scrip master CSV cache |
| `STALE_TTL_MINUTES` | No | 30 | Minutes before stale data is evicted |

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
| DELETE | `/api/contracts/{id}` | Full remove |
| GET | `/api/scrip/expiries?symbol=NIFTY` | Available expiry dates |
| GET | `/api/scrip/strikes?symbol=NIFTY&expiry=2026-04-24` | Strikes for an expiry |
| GET | `/api/search?q=NIFTY&limit=20` | Fuzzy search instruments |
| GET | `/api/tiers` | Current tier configuration |
| POST | `/api/tiers` | Update tier configuration |
| GET | `/api/health` | Health check |
| GET | `/api/slots` | Slot usage breakdown |
| WS | `/ws/fair` | Live FairResult JSON stream |

## Dashboard Tabs

- **Signals** — overvalued (short) and undervalued (long) candidates, sorted by mispricing %
- **By Underlying** — drill into a specific underlying + expiry, see full option chain
- **All Subscribed** — every active instrument with tier badges and cross-exchange tags
- **Search Results** — fuzzy search across ~79,000 scrip master instruments, subscribe with one click

## Tier System

The engine manages subscriptions across 3 WebSocket connections (15,000 instrument slots total):

- **Tier 1** — Index full chains (NIFTY, BANKNIFTY, etc.) — all strikes, all expiries
- **Tier 2** — ATM-centric stocks — nearest N strikes around ATM, auto-rotates as spot moves
- **Tier 3** — Manual one-offs — individual contracts added via dashboard search

Configure tiers via the dashboard's Tier Config panel or `POST /api/tiers`.

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
```
