from unittest.mock import MagicMock
from src.feed.dhan_feed import DhanFeedClient
from src.core.models import Tick

def test_parse_tick_data():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._on_tick = MagicMock()
    client._subscribed = set()

    tick_data = {
        "security_id": 42528, "LTP": 150.5,
        "volume": 1000, "oi": 50000,
        "bid_price": 150.0, "ask_price": 151.0,
    }
    client._handle_tick(tick_data)
    client._on_tick.assert_called_once()
    tick = client._on_tick.call_args[0][0]
    assert isinstance(tick, Tick)
    assert tick.security_id == "42528"
    assert tick.ltp == 150.5

def test_subscribe_adds_to_pending():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._subscribed = set()
    client._feed = None
    client._pending_subscribe = []
    client.subscribe("42528", "NSE_FNO")
    assert ("42528", "NSE_FNO") in client._pending_subscribe

def test_slot_count():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._subscribed = {("42528", "NSE_FNO"), ("13", "IDX_I")}
    assert client.slot_count == 2
    assert client.available_slots == 4998
