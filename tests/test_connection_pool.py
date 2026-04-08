from unittest.mock import MagicMock
from src.feed.connection_pool import ConnectionPool

def test_subscribe_assigns_to_least_loaded():
    pool = ConnectionPool.__new__(ConnectionPool)
    pool._clients = []
    for i in range(3):
        mock = MagicMock()
        mock.slot_count = i * 100
        mock.available_slots = 5000 - i * 100
        mock.subscribe = MagicMock()
        pool._clients.append(mock)
    pool._assignment = {}
    pool.subscribe("42528", "NSE_FNO")
    pool._clients[0].subscribe.assert_called_once_with("42528", "NSE_FNO")
    assert pool._assignment["42528"] == 0

def test_unsubscribe():
    pool = ConnectionPool.__new__(ConnectionPool)
    pool._clients = [MagicMock() for _ in range(3)]
    pool._assignment = {"42528": 1}
    pool.unsubscribe("42528", "NSE_FNO")
    pool._clients[1].unsubscribe.assert_called_once_with("42528", "NSE_FNO")
    assert "42528" not in pool._assignment

def test_total_slots():
    pool = ConnectionPool.__new__(ConnectionPool)
    pool._clients = []
    pool._instruments_per_connection = 5000
    pool._num_connections = 3
    for _ in range(3):
        mock = MagicMock()
        mock.slot_count = 1000
        pool._clients.append(mock)
    assert pool.total_used == 3000
    assert pool.total_capacity == 15000

def test_subscribe_deduplicates():
    pool = ConnectionPool.__new__(ConnectionPool)
    pool._clients = [MagicMock() for _ in range(3)]
    for c in pool._clients:
        c.slot_count = 0
        c.available_slots = 5000
    pool._assignment = {"42528": 0}
    pool.subscribe("42528", "NSE_FNO")
    pool._clients[0].subscribe.assert_not_called()
