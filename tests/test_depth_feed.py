# tests/test_depth_feed.py
import struct
from src.feed.depth_feed import DepthFeedClient
from src.core.models import DepthData, DepthLevel

def test_parse_depth_valid():
    client = DepthFeedClient.__new__(DepthFeedClient)
    # Build fake binary: 12-byte header + 2 bid levels + 2 ask levels
    header = struct.pack('<HBBiI', 100, 23, 2, 42528, 2)  # msg_len, resp_code, exchange, security_id, row_count
    bid1 = struct.pack('<dII', 23500.50, 100, 5)   # price, qty, orders
    bid2 = struct.pack('<dII', 23500.00, 200, 10)
    ask1 = struct.pack('<dII', 23501.00, 150, 8)
    ask2 = struct.pack('<dII', 23501.50, 80, 3)
    data = header + bid1 + bid2 + ask1 + ask2

    result = client._parse_depth(data)
    assert result is not None
    assert result.security_id == "42528"
    assert len(result.bids) == 2
    assert len(result.asks) == 2
    assert result.bids[0].price == 23500.50
    assert result.bids[0].quantity == 100
    assert result.total_bid_depth == 300
    assert result.total_ask_depth == 230
    assert -1 <= result.bid_ask_imbalance <= 1

def test_parse_depth_too_short():
    client = DepthFeedClient.__new__(DepthFeedClient)
    assert client._parse_depth(b'\x00' * 5) is None

def test_set_instruments():
    client = DepthFeedClient.__new__(DepthFeedClient)
    client._lock = __import__('threading').Lock()
    client._subscribed = set()
    instruments = [("42528", "NSE_FNO"), ("13", "IDX_I")]
    client.set_instruments(instruments)
    assert client.instrument_count == 2

def test_max_instruments():
    client = DepthFeedClient.__new__(DepthFeedClient)
    client._lock = __import__('threading').Lock()
    client._subscribed = set()
    instruments = [(str(i), "NSE_FNO") for i in range(100)]
    client.set_instruments(instruments)
    assert client.instrument_count == 50  # capped at MAX_DEPTH_INSTRUMENTS
