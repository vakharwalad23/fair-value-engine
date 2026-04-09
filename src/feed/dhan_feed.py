"""Single Dhan DhanFeed SDK wrapper."""
import asyncio
import logging
import threading
import time
from typing import Callable, Optional

from src.core.models import Tick

logger = logging.getLogger(__name__)

SEGMENT_MAP = {
    "NSE_EQ": 1, "NSE_FNO": 2, "NSE_CURRENCY": 3,
    "BSE_EQ": 4, "BSE_FNO": 5, "MCX_COMM": 7, "IDX_I": 13,
}

SEGMENT_REVERSE = {v: k for k, v in SEGMENT_MAP.items()}


class DhanFeedClient:
    MAX_INSTRUMENTS = 5000
    BATCH_SIZE = 100

    def __init__(self, client_id: str, access_token: str, on_tick: Callable[[Tick], None],
                 connection_id: int = 0, max_instruments: int = 0):
        self._client_id = client_id
        self._access_token = access_token
        self._on_tick = on_tick
        self._connection_id = connection_id
        if max_instruments > 0:
            self.MAX_INSTRUMENTS = max_instruments
        self._lock = threading.Lock()
        self._feed = None
        self._thread: Optional[threading.Thread] = None
        self._subscribed: set[tuple[str, str]] = set()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def slot_count(self) -> int:
        with self._lock:
            return len(self._subscribed)

    @property
    def available_slots(self) -> int:
        with self._lock:
            return self.MAX_INSTRUMENTS - len(self._subscribed)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"Feed {self._connection_id} thread already running, skipping start()")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_forever, name=f"feed-{self._connection_id}", daemon=True)
        self._thread.start()
        logger.info(f"Feed connection {self._connection_id} started with {len(self._subscribed)} instruments")

    def _run_forever(self):
        from dhanhq import DhanFeed
        while self._running:
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                with self._lock:
                    instruments = self._build_instrument_list(list(self._subscribed))
                feed = DhanFeed(
                    client_id=self._client_id,
                    access_token=self._access_token,
                    instruments=instruments,
                )
                with self._lock:
                    self._feed = feed
                self._feed.on_ticks = self._handle_tick
                self._feed.run_forever()
            except Exception as e:
                logger.error(f"Feed {self._connection_id} error: {e}")
            finally:
                with self._lock:
                    self._feed = None
                if loop is not None:
                    try:
                        loop.close()
                    except Exception:
                        pass
                self._loop = None
            if self._running:
                logger.info(f"Feed {self._connection_id} reconnecting in 5s...")
                time.sleep(5)

    def _handle_tick(self, tick_data):
        if isinstance(tick_data, list):
            for item in tick_data:
                self._process_single_tick(item)
        elif isinstance(tick_data, dict):
            self._process_single_tick(tick_data)

    def _process_single_tick(self, data: dict):
        ltp_raw = data.get("LTP") or data.get("ltp")
        if ltp_raw is None:
            return
        ltp = float(ltp_raw)
        if ltp <= 0:
            return
        oi = data.get("OI") or data.get("oi")
        tick = Tick(
            security_id=str(data.get("security_id", "")),
            ltp=ltp,
            oi=int(oi) if oi is not None else None,
            volume=data.get("volume"),
            bid=float(data["bid_price"]) if data.get("bid_price") else None,
            ask=float(data["ask_price"]) if data.get("ask_price") else None,
        )
        self._on_tick(tick)

    def subscribe(self, security_id: str, exchange_segment: str) -> bool:
        pair = (security_id, exchange_segment)
        with self._lock:
            if pair in self._subscribed:
                return False
            if len(self._subscribed) >= self.MAX_INSTRUMENTS:
                logger.warning(f"Feed {self._connection_id} at capacity")
                return False
            self._subscribed.add(pair)
            if self._feed:
                seg_code = SEGMENT_MAP.get(exchange_segment, 2)
                self._feed.subscribe_symbols([(seg_code, str(security_id))])
        return True

    def unsubscribe(self, security_id: str, exchange_segment: str):
        pair = (security_id, exchange_segment)
        with self._lock:
            self._subscribed.discard(pair)
            if self._feed:
                seg_code = SEGMENT_MAP.get(exchange_segment, 2)
                self._feed.unsubscribe_symbols([(seg_code, str(security_id))])

    def _build_instrument_list(self, pairs: list[tuple[str, str]]) -> list[tuple[int, str]]:
        return [(SEGMENT_MAP.get(seg, 2), sid) for sid, seg in pairs]

    def stop(self):
        self._running = False
        with self._lock:
            if self._feed:
                try:
                    self._feed.close_connection()
                except Exception:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
