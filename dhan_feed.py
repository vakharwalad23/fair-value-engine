"""
Dhan Live Market Feed WebSocket Handler
========================================
Connects to Dhan's wss://api-feed.dhan.co endpoint,
subscribes to F&O + underlying instruments, parses
binary packets, and routes ticks to FareEngine.

Supports Quote Packet (code 4) + OI Packet (code 5)
for full derivative data.
"""

import asyncio
import struct
import json
import logging
import time
import websockets
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from fare_engine import FareEngine, Tick

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Packet Response Codes (Dhan Annexure)
# ─────────────────────────────────────────────
RESP_TICKER  = 2
RESP_QUOTE   = 4
RESP_OI      = 5
RESP_PREV    = 6
RESP_FULL    = 8
RESP_DISC    = 50

# Exchange Segment byte codes
EXCHANGE_SEG_MAP = {
    1:  "NSE_EQ",
    2:  "NSE_FNO",
    3:  "NSE_CURRENCY",
    4:  "BSE_EQ",
    5:  "BSE_FNO",
    7:  "MCX_COMM",
    13: "IDX_I",
}

# Request codes
REQ_SUBSCRIBE_QUOTE  = 17   # Quote + OI
REQ_SUBSCRIBE_FULL   = 21   # Full (Quote + Depth + OI)
REQ_SUBSCRIBE_TICKER = 15   # Ticker only
REQ_DISCONNECT       = 12


# ─────────────────────────────────────────────
# Binary Parsers
# ─────────────────────────────────────────────

def parse_header(data: bytes) -> Optional[Dict]:
    """Parse 8-byte response header."""
    if len(data) < 8:
        return None
    resp_code = data[0]
    msg_len   = struct.unpack_from("<h", data, 1)[0]
    exch_seg  = data[3]
    sec_id    = struct.unpack_from("<i", data, 4)[0]
    return {
        "resp_code": resp_code,
        "msg_len": msg_len,
        "exchange_segment": EXCHANGE_SEG_MAP.get(exch_seg, str(exch_seg)),
        "security_id": str(sec_id),
    }


def parse_ticker(data: bytes) -> Optional[Dict]:
    """Parse Ticker Packet (code=2). Total 17 bytes."""
    if len(data) < 17:
        return None
    header = parse_header(data)
    ltp = struct.unpack_from("<f", data, 8)[0]
    ltt = struct.unpack_from("<i", data, 13)[0]
    return {**header, "ltp": ltp, "ltt": ltt}


def parse_quote(data: bytes) -> Optional[Dict]:
    """Parse Quote Packet (code=4). Total 51 bytes."""
    if len(data) < 51:
        return None
    header = parse_header(data)
    ltp     = struct.unpack_from("<f", data,  8)[0]
    ltq     = struct.unpack_from("<h", data, 12)[0]
    ltt     = struct.unpack_from("<i", data, 15)[0]
    atp     = struct.unpack_from("<f", data, 19)[0]
    volume  = struct.unpack_from("<i", data, 23)[0]
    sell_q  = struct.unpack_from("<i", data, 27)[0]
    buy_q   = struct.unpack_from("<i", data, 31)[0]
    d_open  = struct.unpack_from("<f", data, 35)[0]
    d_close = struct.unpack_from("<f", data, 39)[0]
    d_high  = struct.unpack_from("<f", data, 43)[0]
    d_low   = struct.unpack_from("<f", data, 47)[0]
    return {
        **header,
        "ltp": ltp, "ltq": ltq, "ltt": ltt,
        "atp": atp, "volume": volume,
        "total_sell_qty": sell_q, "total_buy_qty": buy_q,
        "open": d_open, "close": d_close,
        "high": d_high, "low": d_low,
    }


def parse_oi(data: bytes) -> Optional[Dict]:
    """Parse OI Packet (code=5). 13 bytes."""
    if len(data) < 13:
        return None
    header = parse_header(data)
    oi = struct.unpack_from("<i", data, 9)[0]
    return {**header, "oi": oi}


def parse_full(data: bytes) -> Optional[Dict]:
    """Parse Full Packet (code=8). 163 bytes."""
    if len(data) < 163:
        return None
    header  = parse_header(data)
    ltp     = struct.unpack_from("<f", data,  8)[0]
    ltq     = struct.unpack_from("<h", data, 12)[0]
    ltt     = struct.unpack_from("<i", data, 15)[0]
    atp     = struct.unpack_from("<f", data, 19)[0]
    volume  = struct.unpack_from("<i", data, 23)[0]
    sell_q  = struct.unpack_from("<i", data, 27)[0]
    buy_q   = struct.unpack_from("<i", data, 31)[0]
    oi      = struct.unpack_from("<i", data, 35)[0]
    oi_high = struct.unpack_from("<i", data, 39)[0]
    oi_low  = struct.unpack_from("<i", data, 43)[0]
    d_open  = struct.unpack_from("<f", data, 47)[0]
    d_close = struct.unpack_from("<f", data, 51)[0]
    d_high  = struct.unpack_from("<f", data, 55)[0]
    d_low   = struct.unpack_from("<f", data, 59)[0]

    depth = []
    offset = 63
    for _ in range(5):
        bid_qty  = struct.unpack_from("<i", data, offset)[0]
        ask_qty  = struct.unpack_from("<i", data, offset+4)[0]
        bid_ord  = struct.unpack_from("<h", data, offset+8)[0]
        ask_ord  = struct.unpack_from("<h", data, offset+10)[0]
        bid_px   = struct.unpack_from("<f", data, offset+12)[0]
        ask_px   = struct.unpack_from("<f", data, offset+16)[0]
        depth.append({
            "bid_qty": bid_qty, "ask_qty": ask_qty,
            "bid_orders": bid_ord, "ask_orders": ask_ord,
            "bid_price": bid_px, "ask_price": ask_px,
        })
        offset += 20

    return {
        **header,
        "ltp": ltp, "ltq": ltq, "ltt": ltt,
        "atp": atp, "volume": volume,
        "total_sell_qty": sell_q, "total_buy_qty": buy_q,
        "oi": oi, "oi_high": oi_high, "oi_low": oi_low,
        "open": d_open, "close": d_close,
        "high": d_high, "low": d_low,
        "depth": depth,
    }


# ─────────────────────────────────────────────
# Feed Client
# ─────────────────────────────────────────────

@dataclass
class SubscribeEntry:
    security_id: str
    exchange_segment: str


class DhanFeedClient:
    """
    WebSocket client for Dhan Live Market Feed.
    Parses binary packets and routes ticks to FareEngine.
    
    Usage:
        client = DhanFeedClient(
            client_id="your_client_id",
            access_token="your_token",
            engine=fare_engine,
            mode="QUOTE",          # TICKER | QUOTE | FULL
        )
        client.subscribe([
            SubscribeEntry("13",   "IDX_I"),    # NIFTY spot
            SubscribeEntry("35001","NSE_FNO"),  # some option
        ])
        await client.run()
    """

    WS_URL = "wss://api-feed.dhan.co"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        engine: FareEngine,
        mode: str = "QUOTE",
        on_raw_tick: Optional[Callable[[Dict], None]] = None,
    ):
        self.client_id    = client_id
        self.access_token = access_token
        self.engine       = engine
        self.mode         = mode
        self.on_raw_tick  = on_raw_tick

        self._instruments: List[SubscribeEntry] = []
        self._ws          = None
        self._running     = False
        self._oi_cache: Dict[str, int] = {}  # security_id -> last OI

        self._req_code = {
            "TICKER": REQ_SUBSCRIBE_TICKER,
            "QUOTE":  REQ_SUBSCRIBE_QUOTE,
            "FULL":   REQ_SUBSCRIBE_FULL,
        }.get(mode.upper(), REQ_SUBSCRIBE_QUOTE)

    def subscribe(self, instruments: List[SubscribeEntry]):
        self._instruments.extend(instruments)

    def _build_url(self) -> str:
        return (
            f"{self.WS_URL}"
            f"?version=2"
            f"&token={self.access_token}"
            f"&clientId={self.client_id}"
            f"&authType=2"
        )

    def _build_subscribe_msg(self, batch: List[SubscribeEntry]) -> str:
        return json.dumps({
            "RequestCode": self._req_code,
            "InstrumentCount": len(batch),
            "InstrumentList": [
                {
                    "ExchangeSegment": e.exchange_segment,
                    "SecurityId": e.security_id,
                }
                for e in batch
            ],
        })

    def _dispatch(self, parsed: Dict):
        """Convert parsed packet to Tick and push to engine."""
        if "ltp" not in parsed:
            return

        security_id = parsed["security_id"]
        ltp = parsed["ltp"]

        if ltp <= 0:
            return

        oi = parsed.get("oi") or self._oi_cache.get(security_id)

        # Get bid/ask from depth if available
        depth = parsed.get("depth", [])
        bid = depth[0]["bid_price"] if depth else None
        ask = depth[0]["ask_price"] if depth else None

        tick = Tick(
            security_id=security_id,
            ltp=ltp,
            timestamp=time.time(),
            oi=oi,
            volume=parsed.get("volume"),
            bid=bid,
            ask=ask,
        )
        self.engine.on_tick(tick)

        if self.on_raw_tick:
            self.on_raw_tick(parsed)

    def _handle_oi_packet(self, parsed: Dict):
        """Cache OI data for next tick merge."""
        if parsed:
            sid = parsed["security_id"]
            self._oi_cache[sid] = parsed.get("oi", 0)

    async def _send_subscriptions(self, ws):
        """Send instrument list in batches of 100."""
        batch_size = 100
        for i in range(0, len(self._instruments), batch_size):
            batch = self._instruments[i:i+batch_size]
            msg = self._build_subscribe_msg(batch)
            await ws.send(msg)
            logger.info(f"Subscribed batch {i//batch_size + 1}: {len(batch)} instruments")
            await asyncio.sleep(0.1)

    async def run(self):
        """Connect and keep running with auto-reconnect."""
        self._running = True
        reconnect_delay = 2

        while self._running:
            try:
                url = self._build_url()
                logger.info(f"Connecting to Dhan feed: {url[:60]}...")

                async with websockets.connect(url, ping_interval=10) as ws:
                    self._ws = ws
                    reconnect_delay = 2  # reset on success
                    await self._send_subscriptions(ws)

                    async for message in ws:
                        if isinstance(message, bytes):
                            await self._process_binary(message)
                        # text pings are handled by library automatically

            except websockets.exceptions.ConnectionClosedError as e:
                logger.warning(f"Connection closed: {e}. Reconnecting in {reconnect_delay}s...")
            except Exception as e:
                logger.error(f"Feed error: {e}. Reconnecting in {reconnect_delay}s...")

            if self._running:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def _process_binary(self, data: bytes):
        """Dispatch binary packet based on response code."""
        if len(data) < 1:
            return

        resp_code = data[0]

        try:
            if resp_code == RESP_TICKER:
                parsed = parse_ticker(data)
                if parsed:
                    self._dispatch(parsed)

            elif resp_code == RESP_QUOTE:
                parsed = parse_quote(data)
                if parsed:
                    self._dispatch(parsed)

            elif resp_code == RESP_OI:
                parsed = parse_oi(data)
                if parsed:
                    self._handle_oi_packet(parsed)

            elif resp_code == RESP_FULL:
                parsed = parse_full(data)
                if parsed:
                    self._dispatch(parsed)

            elif resp_code == RESP_DISC:
                code = struct.unpack_from("<h", data, 9)[0] if len(data) >= 11 else 0
                logger.error(f"Disconnected by server. Code: {code}")

        except Exception as e:
            logger.error(f"Packet parse error (code={resp_code}): {e}")

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.send(json.dumps({"RequestCode": REQ_DISCONNECT}))
            await self._ws.close()
