"""Connection pool managing multiple DhanFeedClient instances."""
import logging
import threading
from typing import Callable

from src.core.models import Tick
from src.feed.dhan_feed import DhanFeedClient

logger = logging.getLogger(__name__)


class ConnectionPool:
    def __init__(self, client_id: str, access_token: str, on_tick: Callable[[Tick], None],
                 num_connections: int = 3, instruments_per_connection: int = 5000):
        self._on_tick = on_tick
        self._num_connections = num_connections
        self._instruments_per_connection = instruments_per_connection
        self._lock = threading.Lock()
        self._clients: list[DhanFeedClient] = []
        self._assignment: dict[str, int] = {}

        for i in range(num_connections):
            client = DhanFeedClient(
                client_id=client_id, access_token=access_token,
                on_tick=on_tick, connection_id=i,
                max_instruments=instruments_per_connection,
            )
            self._clients.append(client)

    @property
    def total_used(self) -> int:
        return sum(c.slot_count for c in self._clients)

    @property
    def total_capacity(self) -> int:
        return self._num_connections * self._instruments_per_connection

    @property
    def total_available(self) -> int:
        return self.total_capacity - self.total_used

    def per_connection_usage(self) -> list[dict]:
        return [{"connection_id": i, "used": c.slot_count, "capacity": c.MAX_INSTRUMENTS} for i, c in enumerate(self._clients)]

    def start(self):
        import time
        for i, client in enumerate(self._clients):
            if i > 0:
                time.sleep(2)  # stagger connections to avoid Dhan rate limiting
            client.start()

    def subscribe(self, security_id: str, exchange_segment: str) -> bool:
        with self._lock:
            if security_id in self._assignment:
                return True
            best = None
            best_count = float("inf")
            for i, client in enumerate(self._clients):
                if client.available_slots > 0 and client.slot_count < best_count:
                    best = i
                    best_count = client.slot_count
            if best is None:
                logger.warning(f"No capacity for {security_id}")
                return False
            ok = self._clients[best].subscribe(security_id, exchange_segment)
            if ok:
                self._assignment[security_id] = best
            return ok

    def unsubscribe(self, security_id: str, exchange_segment: str):
        with self._lock:
            idx = self._assignment.pop(security_id, None)
            if idx is not None:
                self._clients[idx].unsubscribe(security_id, exchange_segment)

    def subscribe_batch(self, instruments: list[tuple[str, str]]) -> int:
        count = 0
        for sec_id, seg in instruments:
            if self.subscribe(sec_id, seg):
                count += 1
        return count

    def unsubscribe_batch(self, instruments: list[tuple[str, str]]):
        for sec_id, seg in instruments:
            self.unsubscribe(sec_id, seg)

    def stop(self):
        for client in self._clients:
            client.stop()
