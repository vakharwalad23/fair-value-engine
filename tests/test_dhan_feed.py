import threading
from unittest.mock import MagicMock
from src.feed.dhan_feed import DhanFeedClient
from src.core.models import Tick

def test_parse_tick_data():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._on_tick = MagicMock()
    client._subscribed = set()
    client._lock = threading.Lock()

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

def test_subscribe_tracks_in_subscribed():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._subscribed = set()
    client._feed = None
    client._lock = threading.Lock()
    client._connection_id = 0
    client.MAX_INSTRUMENTS = 5000
    result = client.subscribe("42528", "NSE_FNO")
    assert result is True
    assert ("42528", "NSE_FNO") in client._subscribed

def test_subscribe_returns_false_on_duplicate():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._subscribed = {("42528", "NSE_FNO")}
    client._feed = None
    client._lock = threading.Lock()
    client._connection_id = 0
    client.MAX_INSTRUMENTS = 5000
    result = client.subscribe("42528", "NSE_FNO")
    assert result is False

def test_subscribe_returns_false_at_capacity():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._subscribed = set()
    client._feed = None
    client._lock = threading.Lock()
    client._connection_id = 0
    client.MAX_INSTRUMENTS = 0
    result = client.subscribe("42528", "NSE_FNO")
    assert result is False
    assert ("42528", "NSE_FNO") not in client._subscribed

def test_slot_count():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._lock = threading.Lock()
    client._subscribed = {("42528", "NSE_FNO"), ("13", "IDX_I")}
    client.MAX_INSTRUMENTS = 5000
    assert client.slot_count == 2
    assert client.available_slots == 4998

def test_start_skips_if_thread_alive():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._running = True
    client._connection_id = 0
    client._subscribed = set()
    client._lock = threading.Lock()
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True
    client._thread = mock_thread
    client.start()
    # Should not have created a new thread
    assert client._thread is mock_thread

def test_stop_joins_thread():
    client = DhanFeedClient.__new__(DhanFeedClient)
    client._running = True
    client._feed = None
    client._lock = threading.Lock()
    mock_thread = MagicMock()
    client._thread = mock_thread
    client.stop()
    assert client._running is False
    mock_thread.join.assert_called_once_with(timeout=10)
    assert client._thread is None
