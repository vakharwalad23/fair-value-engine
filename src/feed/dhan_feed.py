"""Single Dhan MarketFeed SDK wrapper."""
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

    def __init__(self, client_id: str, access_token: str, on_tick: Callable[[Tick], None], connection_id: int = 0):
        self._client_id = client_id
        self._access_token = access_token
        self._on_tick = on_tick
        self._connection_id = connection_id
        self._feed = None
        self._thread: Optional[threading.Thread] = None
        self._subscribed: set[tuple[str, str]] = set()
        self._pending_subscribe: list[tuple[str, str]] = []
        self._running = False

    @property
    def slot_count(self) -> int:
        return len(self._subscribed)

    @property
    def available_slots(self) -> int:
        return self.MAX_INSTRUMENTS - self.slot_count

    def start(self):
        from dhanhq import MarketFeed
        instruments = self._build_instrument_list(list(self._subscribed))
        self._feed = MarketFeed(
            client_id=self._client_id, access_token=self._access_token,
            instruments=instruments, subscription_code=MarketFeed.Full,
        )
        self._feed.on_ticks = self._handle_tick
        self._feed.on_close = self._handle_close
        self._running = True
        self._thread = threading.Thread(target=self._run_forever, name=f"feed-{self._connection_id}", daemon=True)
        self._thread.start()
        logger.info(f"Feed connection {self._connection_id} started with {len(self._subscribed)} instruments")

    def _run_forever(self):
        try:
            self._feed.run_forever()
        except Exception as e:
            logger.error(f"Feed {self._connection_id} error: {e}")
            if self._running:
                time.sleep(5)
                self.start()

    def _handle_tick(self, tick_data):
        if isinstance(tick_data, list):
            for item in tick_data:
                self._process_single_tick(item)
        elif isinstance(tick_data, dict):
            self._process_single_tick(tick_data)

    def _process_single_tick(self, data: dict):
        ltp = data.get("LTP") or data.get("ltp")
        if ltp is None or ltp <= 0:
            return
        tick = Tick(
            security_id=str(data.get("security_id", "")),
            ltp=float(ltp), oi=data.get("oi"),
            volume=data.get("volume"), bid=data.get("bid_price"), ask=data.get("ask_price"),
        )
        self._on_tick(tick)

    def _handle_close(self, *args):
        logger.warning(f"Feed {self._connection_id} connection closed")

    def subscribe(self, security_id: str, exchange_segment: str):
        pair = (security_id, exchange_segment)
        if pair in self._subscribed:
            return
        if self.slot_count >= self.MAX_INSTRUMENTS:
            logger.warning(f"Feed {self._connection_id} at capacity")
            return
        self._subscribed.add(pair)
        if self._feed:
            seg_code = SEGMENT_MAP.get(exchange_segment, 2)
            self._feed.subscribe_symbols([(seg_code, str(security_id))])
        else:
            self._pending_subscribe.append(pair)

    def unsubscribe(self, security_id: str, exchange_segment: str):
        pair = (security_id, exchange_segment)
        self._subscribed.discard(pair)
        if self._feed:
            seg_code = SEGMENT_MAP.get(exchange_segment, 2)
            self._feed.unsubscribe_symbols([(seg_code, str(security_id))])

    def _build_instrument_list(self, pairs: list[tuple[str, str]]) -> list[tuple[int, str]]:
        return [(SEGMENT_MAP.get(seg, 2), sid) for sid, seg in pairs]

    def stop(self):
        self._running = False
        if self._feed:
            try:
                self._feed.close()
            except Exception:
                pass
