"""Slot usage tracking and capacity forecasting."""
import threading


class SlotTracker:
    def __init__(self, total_slots: int = 15000):
        self._total = total_slots
        self._slots: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return len(self._slots)

    @property
    def total(self) -> int:
        return self._total

    @property
    def available(self) -> int:
        return self._total - self.used

    def add(self, security_id: str, tier: int):
        with self._lock:
            self._slots[security_id] = tier

    def remove(self, security_id: str):
        with self._lock:
            self._slots.pop(security_id, None)

    def contains(self, security_id: str) -> bool:
        with self._lock:
            return security_id in self._slots

    def per_tier(self) -> dict[int, int]:
        with self._lock:
            counts = {1: 0, 2: 0, 3: 0}
            for tier in self._slots.values():
                counts[tier] = counts.get(tier, 0) + 1
            return counts

    def forecast(self, new_count: int) -> dict:
        with self._lock:
            used = len(self._slots)
            available = self._total - used
            return {
                "slots_needed": new_count, "slots_used": used,
                "slots_after": available - new_count, "fits": new_count <= available,
            }

    def to_dict(self) -> dict:
        with self._lock:
            used = len(self._slots)
            counts = {1: 0, 2: 0, 3: 0}
            for tier in self._slots.values():
                counts[tier] = counts.get(tier, 0) + 1
            return {"used": used, "total": self._total, "available": self._total - used, "per_tier": counts}
