"""F&O Fair Value Engine — FastAPI Server"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.config import settings
from src.core.fair_engine import FairEngine
from src.core.models import FairResult
from src.scrip.scrip_master import ScripMaster
from src.search.fuzzy_index import FuzzyIndex
from src.feed.connection_pool import ConnectionPool
from src.subscription.slot_tracker import SlotTracker
from src.subscription.tier_config import TierConfig
from src.subscription.rotation_manager import RotationManager

from src.api.routes import fair as fair_routes
from src.api.routes import contracts as contract_routes
from src.api.routes import scrip as scrip_routes
from src.api.routes import search as search_routes
from src.api.routes import tiers as tier_routes
from src.api.routes import health as health_routes

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL), format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

engine = FairEngine()
scrip_master = ScripMaster(cache_dir=settings.SCRIP_CACHE_DIR)
fuzzy_index = FuzzyIndex()
slot_tracker = SlotTracker(total_slots=settings.total_slots)
tier_config = TierConfig(config_path=f"{settings.SCRIP_CACHE_DIR}/tier_config.json")
connection_pool = None
rotation_manager = None

ws_clients: set[WebSocket] = set()
_ws_lock = asyncio.Lock()
_event_loop = None


async def broadcast_fair(result: FairResult):
    from src.api.routes.fair import _to_response
    msg = _to_response(result)
    dead = []
    async with _ws_lock:
        snapshot = list(ws_clients)
    for ws in snapshot:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    if dead:
        async with _ws_lock:
            for ws in dead:
                ws_clients.discard(ws)


def fair_callback(result: FairResult):
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_fair(result), _event_loop)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global connection_pool, rotation_manager, _event_loop

    _event_loop = asyncio.get_running_loop()

    engine.on_fair_update(fair_callback)

    logger.info("Loading scrip master...")
    try:
        scrip_master.load()
        scrip_master.schedule_daily_refresh()
    except Exception:
        logger.exception("Failed to load scrip master — starting in degraded mode")

    logger.info("Building fuzzy search index...")
    try:
        fuzzy_index.build(scrip_master.dataframe)
    except Exception:
        logger.exception("Failed to build fuzzy index — search disabled")

    if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:
        connection_pool = ConnectionPool(
            client_id=settings.DHAN_CLIENT_ID, access_token=settings.DHAN_ACCESS_TOKEN,
            on_tick=engine.on_tick, num_connections=settings.MAX_CONNECTIONS,
        )

        tier_config.load()

        rotation_manager = RotationManager(
            engine=engine, pool=connection_pool, scrip_master=scrip_master,
            slot_tracker=slot_tracker, tier_config=tier_config,
            stale_ttl=settings.STALE_TTL_MINUTES * 60,
        )
        rotation_manager.apply_tier1()
        rotation_manager.apply_tier2()
        rotation_manager.restore_tier3()

        connection_pool.start()
        logger.info(f"Feed started: {slot_tracker.used} instruments subscribed")
    else:
        logger.warning("No Dhan credentials — feed disabled. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")

    # Wire singletons to route modules
    fair_routes.engine = engine
    contract_routes.engine = engine
    contract_routes.scrip_master = scrip_master
    contract_routes.connection_pool = connection_pool
    contract_routes.slot_tracker = slot_tracker
    contract_routes.tier_config = tier_config
    scrip_routes.scrip_master = scrip_master
    search_routes.fuzzy_index = fuzzy_index
    search_routes.slot_tracker = slot_tracker
    tier_routes.tier_config = tier_config
    health_routes.engine = engine
    health_routes.slot_tracker = slot_tracker
    health_routes.connection_pool = connection_pool

    yield

    _event_loop = None

    if connection_pool:
        connection_pool.stop()
    scrip_master.stop()
    engine.stop()


app = FastAPI(title="F&O Fair Engine", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(fair_routes.router)
app.include_router(contract_routes.router)
app.include_router(scrip_routes.router)
app.include_router(search_routes.router)
app.include_router(tier_routes.router)
app.include_router(health_routes.router)


@app.get("/")
def index():
    return FileResponse("static/dashboard.html")


@app.websocket("/ws/fair")
async def ws_fair(websocket: WebSocket):
    await websocket.accept()
    async with _ws_lock:
        ws_clients.add(websocket)
    logger.info(f"WS connected. Total: {len(ws_clients)}")

    from src.api.routes.fair import _to_response
    for result in engine.get_all_results():
        await websocket.send_json(_to_response(result))

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        async with _ws_lock:
            ws_clients.discard(websocket)
        logger.info(f"WS disconnected. Total: {len(ws_clients)}")
