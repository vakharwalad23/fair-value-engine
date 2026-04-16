"""20-level market depth WebSocket client for Dhan."""
import asyncio
import json
import logging
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from src.core.models import DepthData, DepthLevel
from src.utils.market_hours import is_market_open, seconds_until_market_open

logger = logging.getLogger(__name__)

DEPTH_WSS_URL = "wss://depth-api-feed.dhan.co/twentydepth"
MAX_DEPTH_INSTRUMENTS = 50
DEPTH_LEVELS = 20
ROTATION_INTERVAL = 30  # seconds


class DepthFeedClient:
    """Connects to Dhan's 20-level depth WebSocket. Max 50 instruments."""

    def __init__(self, client_id: str, access_token: str, on_depth: Callable[[DepthData], None]):
        self._client_id = client_id
        self._access_token = access_token
        self._on_depth = on_depth
        self._lock = threading.Lock()
        self._subscribed: set[tuple[str, str]] = set()  # (security_id, segment)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws = None

    @property
    def instrument_count(self) -> int:
        with self._lock:
            return len(self._subscribed)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_forever, name="depth-feed", daemon=True)
        self._thread.start()
        logger.info(f"Depth feed started with {self.instrument_count} instruments")

    def set_instruments(self, instruments: list[tuple[str, str]]):
        """Bulk replace subscribed instruments (for rotation)."""
        with self._lock:
            self._subscribed = set(instruments[:MAX_DEPTH_INSTRUMENTS])

    def _run_forever(self):
        import websockets.sync.client as ws_client
        backoff = 5
        while self._running:
            try:
                with self._lock:
                    if not self._subscribed:
                        time.sleep(5)
                        continue

                url = f"{DEPTH_WSS_URL}?token={self._access_token}&clientId={self._client_id}&authType=2"
                with ws_client.connect(url, additional_headers={"User-Agent": "DhanFeed/2.0"}) as ws:
                    self._ws = ws
                    logger.info("Depth feed connected")
                    backoff = 5

                    # Subscribe instruments
                    with self._lock:
                        instruments = list(self._subscribed)
                    self._send_subscribe(ws, instruments)

                    # Receive loop
                    while self._running:
                        try:
                            data = ws.recv(timeout=15)
                            if isinstance(data, bytes) and len(data) > 12:
                                depth = self._parse_depth(data)
                                if depth:
                                    self._on_depth(depth)
                        except TimeoutError:
                            continue
                        except Exception as e:
                            logger.warning(f"Depth feed recv error: {e}")
                            break

            except Exception as e:
                logger.error(f"Depth feed error: {e}")
            finally:
                self._ws = None

            if self._running:
                if not is_market_open():
                    wait = seconds_until_market_open()
                    logger.info(f"Depth feed market closed. Sleeping {wait/3600:.1f}h")
                    while wait > 0 and self._running:
                        time.sleep(min(60, wait))
                        wait -= 60
                    continue
                logger.info(f"Depth feed reconnecting in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _send_subscribe(self, ws, instruments: list[tuple[str, str]]):
        """Send subscription request for instruments."""
        SEGMENT_NAMES = {
            "IDX_I": "IDX_I", "NSE_EQ": "NSE_EQ", "NSE_FNO": "NSE_FNO",
            "NSE_CURRENCY": "NSE_CURRENCY", "BSE_EQ": "BSE_EQ",
            "MCX_COMM": "MCX_COMM", "BSE_FNO": "BSE_FNO",
        }
        inst_list = []
        for sec_id, seg in instruments:
            seg_name = SEGMENT_NAMES.get(seg, seg)
            inst_list.append({"ExchangeSegment": seg_name, "SecurityId": str(sec_id)})

        msg = json.dumps({
            "RequestCode": 23,
            "InstrumentCount": len(inst_list),
            "InstrumentList": inst_list,
        })
        ws.send(msg)
        logger.info(f"Depth feed subscribed {len(inst_list)} instruments")

    def _parse_depth(self, data: bytes) -> Optional[DepthData]:
        """Parse binary depth response: 12-byte header + 16 bytes per level."""
        if len(data) < 12:
            return None
        try:
            # Header: 2 bytes msg_len, 1 byte resp_code, 1 byte exchange, 4 bytes security_id, 4 bytes row_count
            msg_len = struct.unpack_from('<H', data, 0)[0]
            resp_code = data[2]
            exchange = data[3]
            security_id = str(struct.unpack_from('<I', data, 4)[0])
            row_count = struct.unpack_from('<I', data, 8)[0]

            offset = 12
            bids = []
            asks = []

            # Parse bid levels
            for _ in range(min(DEPTH_LEVELS, row_count)):
                if offset + 16 > len(data):
                    break
                price = struct.unpack_from('<d', data, offset)[0]
                qty = struct.unpack_from('<I', data, offset + 8)[0]
                orders = struct.unpack_from('<I', data, offset + 12)[0]
                bids.append(DepthLevel(price=round(price, 2), quantity=qty, orders=orders))
                offset += 16

            # Parse ask levels
            for _ in range(min(DEPTH_LEVELS, row_count)):
                if offset + 16 > len(data):
                    break
                price = struct.unpack_from('<d', data, offset)[0]
                qty = struct.unpack_from('<I', data, offset + 8)[0]
                orders = struct.unpack_from('<I', data, offset + 12)[0]
                asks.append(DepthLevel(price=round(price, 2), quantity=qty, orders=orders))
                offset += 16

            total_bid = sum(b.quantity for b in bids)
            total_ask = sum(a.quantity for a in asks)
            imbalance = 0.0
            if total_bid + total_ask > 0:
                imbalance = round((total_bid - total_ask) / (total_bid + total_ask), 4)

            return DepthData(
                security_id=security_id,
                bids=bids,
                asks=asks,
                total_bid_depth=total_bid,
                total_ask_depth=total_ask,
                bid_ask_imbalance=imbalance,
            )
        except Exception as e:
            logger.debug(f"Depth parse error: {e}")
            return None

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=10)
