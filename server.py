"""
F&O Fare API Server
====================
FastAPI server exposing:

  GET  /api/contracts          - List all registered contracts
  GET  /api/fare               - All current FareResults
  GET  /api/fare/{security_id} - Single contract result
  GET  /api/fare/signals       - Only OVERVALUED / UNDERVALUED
  GET  /api/history/{id}       - Historical results for a security
  POST /api/contracts/add      - Add a new contract to track
  POST /api/intervals          - Set snapshot intervals
  WS   /ws/fare                - Live stream of FareResult updates

Run:
    uvicorn server:app --reload --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Optional
from datetime import date

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from fare_engine import FareEngine, ContractMeta, ContractType, FareResult
from dhan_feed import DhanFeedClient, SubscribeEntry
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────
engine = FareEngine()
feed_client: Optional[DhanFeedClient] = None
ws_clients: List[WebSocket] = []


async def broadcast_fare(result: FareResult):
    """Push FareResult JSON to all connected dashboard websocket clients."""
    msg = {
        "security_id": result.security_id,
        "symbol": result.symbol,
        "type": result.contract_type,
        "strike": result.strike,
        "expiry": result.expiry,
        "market_price": result.market_price,
        "fair_value": result.fair_value,
        "mispricing": result.mispricing,
        "mispricing_pct": result.mispricing_pct,
        "signal": result.signal,
        "signal_strength": result.signal_strength,
        "delta": result.delta,
        "gamma": result.gamma,
        "theta": result.theta,
        "vega": result.vega,
        "iv": result.implied_volatility,
        "underlying_price": result.underlying_price,
        "tte_years": result.time_to_expiry,
        "calculated_at": result.calculated_at,
    }
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


def fare_callback(result: FareResult):
    """Called by engine on every tick-level update."""
    asyncio.get_event_loop().call_soon_threadsafe(
        asyncio.ensure_future, broadcast_fare(result)
    )


engine.on_fare_update(fare_callback)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Dhan feed on startup."""
    global feed_client
    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        feed_client = DhanFeedClient(
            client_id=settings.DHAN_CLIENT_ID,
            access_token=settings.DHAN_ACCESS_TOKEN,
            engine=engine,
            mode=settings.FEED_MODE,
        )
        # Subscribe all instruments from pre-loaded contracts
        instruments = []
        for meta in engine._contracts.values():
            instruments.append(SubscribeEntry(meta.security_id, meta.exchange_segment))
            instruments.append(SubscribeEntry(meta.underlying_security_id, _underlying_segment(meta)))
        if instruments:
            # deduplicate
            seen = set()
            unique = []
            for i in instruments:
                key = (i.security_id, i.exchange_segment)
                if key not in seen:
                    seen.add(key)
                    unique.append(i)
            feed_client.subscribe(unique)
        asyncio.create_task(feed_client.run())
        logger.info("Dhan feed client started.")
    else:
        logger.warning("No Dhan credentials — running in simulation mode.")
        asyncio.create_task(_simulate_feed())
    yield
    if feed_client:
        await feed_client.stop()
    engine.stop()


def _underlying_segment(meta: ContractMeta) -> str:
    if meta.underlying_symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
        return "IDX_I"
    return "NSE_EQ"


app = FastAPI(title="F&O Fare Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─────────────────────────────────────────────
# Simulation mode (no credentials)
# ─────────────────────────────────────────────
import random
import math as _math

async def _simulate_feed():
    """Fake price feed for testing without live credentials."""
    from fare_engine import Tick
    t = 0
    while True:
        await asyncio.sleep(0.5)
        t += 0.5
        # Simulate NIFTY spot
        nifty = 23500 + 200 * _math.sin(t / 60) + random.gauss(0, 10)
        engine.on_tick(Tick("13", round(nifty, 2)))

        # Simulate a few contracts
        for sid, K in [("42528", 23500), ("42529", 23500), ("42530", 23600)]:
            intrinsic = max(0, nifty - K) + random.gauss(0, 5)
            ltp = max(0.05, intrinsic + random.uniform(10, 100))
            engine.on_tick(Tick(sid, round(ltp, 2)))


# ─────────────────────────────────────────────
# Pydantic request models
# ─────────────────────────────────────────────

class ContractAddRequest(BaseModel):
    security_id: str
    symbol: str
    contract_type: str          # CE / PE / FUT
    strike: Optional[float] = None
    expiry: str                 # YYYY-MM-DD
    underlying_security_id: str
    underlying_symbol: str
    exchange_segment: str
    lot_size: int = 1
    risk_free_rate: float = 0.065


class IntervalRequest(BaseModel):
    interval_seconds: float


# ─────────────────────────────────────────────
# REST Endpoints
# ─────────────────────────────────────────────

@app.get("/api/contracts")
def list_contracts():
    with engine._lock:
        return [
            {
                "security_id": m.security_id,
                "symbol": m.symbol,
                "type": m.contract_type,
                "strike": m.strike,
                "expiry": m.expiry.isoformat(),
                "underlying": m.underlying_symbol,
                "exchange_segment": m.exchange_segment,
                "lot_size": m.lot_size,
            }
            for m in engine._contracts.values()
        ]


@app.post("/api/contracts/add", status_code=201)
def add_contract(req: ContractAddRequest, background_tasks: BackgroundTasks):
    try:
        ct = ContractType(req.contract_type.upper())
    except ValueError:
        raise HTTPException(400, f"Invalid contract_type: {req.contract_type}")

    meta = ContractMeta(
        security_id=req.security_id,
        symbol=req.symbol,
        contract_type=ct,
        strike=req.strike,
        expiry=date.fromisoformat(req.expiry),
        underlying_security_id=req.underlying_security_id,
        underlying_symbol=req.underlying_symbol,
        exchange_segment=req.exchange_segment,
        lot_size=req.lot_size,
        risk_free_rate=req.risk_free_rate,
    )
    engine.register_contract(meta)

    # Subscribe to feed if running
    if feed_client:
        feed_client.subscribe([
            SubscribeEntry(req.security_id, req.exchange_segment),
            SubscribeEntry(req.underlying_security_id, _underlying_segment(meta)),
        ])

    return {"status": "registered", "security_id": req.security_id}


@app.get("/api/fare")
def get_all_fare():
    results = engine.get_all_results()
    return [_fare_to_dict(r) for r in sorted(results, key=lambda r: -r.signal_strength)]


@app.get("/api/fare/signals")
def get_signals(min_pct: float = 1.0):
    """Returns only mis-priced contracts beyond threshold."""
    results = engine.get_all_results()
    filtered = [r for r in results if abs(r.mispricing_pct) >= min_pct]
    return [_fare_to_dict(r) for r in sorted(filtered, key=lambda r: -r.signal_strength)]


@app.get("/api/fare/{security_id}")
def get_fare(security_id: str):
    result = engine.get_result(security_id)
    if not result:
        raise HTTPException(404, "No fare data for this security_id yet.")
    return _fare_to_dict(result)


@app.get("/api/history/{security_id}")
def get_history(security_id: str, limit: int = 100):
    history = engine.get_history(security_id)
    return [_fare_to_dict(r) for r in history[-limit:]]


@app.post("/api/intervals")
def set_interval(req: IntervalRequest):
    """Register a server-log snapshot at custom interval."""
    def log_snapshot(results: List[FareResult]):
        signals = [r for r in results if r.signal != "FAIR"]
        logger.info(f"[Snapshot] {len(results)} contracts, {len(signals)} signals")
        for r in sorted(signals, key=lambda r: -r.signal_strength)[:5]:
            logger.info(f"  {r.signal:>11} {r.symbol:<25} mis={r.mispricing_pct:+.2f}%")

    engine.on_snapshot(req.interval_seconds, log_snapshot)
    return {"status": "ok", "interval_seconds": req.interval_seconds}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "contracts_loaded": len(engine._contracts),
        "fare_results": len(engine._results),
        "ws_clients": len(ws_clients),
    }


# ─────────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────────

@app.websocket("/ws/fare")
async def ws_fare(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    logger.info(f"Dashboard WS connected. Total: {len(ws_clients)}")

    # Send current snapshot immediately
    for result in engine.get_all_results():
        await websocket.send_json(_fare_to_dict(result))

    try:
        while True:
            # Keep alive — client can send ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_clients.remove(websocket)
        logger.info(f"Dashboard WS disconnected. Total: {len(ws_clients)}")


# ─────────────────────────────────────────────
# Serve dashboard
# ─────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("dashboard.html")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _fare_to_dict(r: FareResult) -> dict:
    return {
        "security_id": r.security_id,
        "symbol": r.symbol,
        "type": r.contract_type,
        "strike": r.strike,
        "expiry": r.expiry,
        "market_price": r.market_price,
        "fair_value": r.fair_value,
        "mispricing": r.mispricing,
        "mispricing_pct": r.mispricing_pct,
        "signal": r.signal,
        "signal_strength": r.signal_strength,
        "delta": r.delta,
        "gamma": r.gamma,
        "theta": r.theta,
        "vega": r.vega,
        "iv": r.implied_volatility,
        "underlying_price": r.underlying_price,
        "tte_years": r.time_to_expiry,
        "calculated_at": r.calculated_at,
    }
