"""Tier configuration with JSON persistence."""
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIER1 = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"]


class TierConfig:
    def __init__(self, config_path: str = "cache/tier_config.json"):
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self.tier1_underlyings: list[str] = list(DEFAULT_TIER1)
        self.tier2_stocks: list[str] = []
        self.tier2_atm_range: int = 10
        self.tier2_expiry_count: int = 2
        self.tier3_contracts: list[dict] = []

    def load(self):
        if not self.config_path.exists():
            logger.info("No tier config file found, using defaults")
            return
        try:
            data = json.loads(self.config_path.read_text())
            with self._lock:
                self.tier1_underlyings = data.get("tier1_underlyings", self.tier1_underlyings)
                self.tier2_stocks = data.get("tier2_stocks", self.tier2_stocks)
                self.tier2_atm_range = data.get("tier2_atm_range", self.tier2_atm_range)
                self.tier2_expiry_count = data.get("tier2_expiry_count", self.tier2_expiry_count)
                self.tier3_contracts = data.get("tier3_contracts", self.tier3_contracts)
            logger.info(f"Tier config loaded: T1={len(self.tier1_underlyings)} T2={len(self.tier2_stocks)} T3={len(self.tier3_contracts)}")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load tier config: {e}")

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".tmp")
        with self._lock:
            data = self.to_dict(locked=True)
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(self.config_path)

    def add_tier3(self, security_id: str, exchange_segment: str):
        entry = {"security_id": security_id, "exchange_segment": exchange_segment}
        with self._lock:
            if not any(c["security_id"] == security_id for c in self.tier3_contracts):
                self.tier3_contracts.append(entry)

    def remove_tier3(self, security_id: str):
        with self._lock:
            self.tier3_contracts = [c for c in self.tier3_contracts if c["security_id"] != security_id]

    def to_dict(self, locked: bool = False) -> dict:
        if locked:
            return {
                "tier1_underlyings": self.tier1_underlyings, "tier2_stocks": self.tier2_stocks,
                "tier2_atm_range": self.tier2_atm_range, "tier2_expiry_count": self.tier2_expiry_count,
                "tier3_contracts": self.tier3_contracts,
            }
        with self._lock:
            return {
                "tier1_underlyings": self.tier1_underlyings, "tier2_stocks": self.tier2_stocks,
                "tier2_atm_range": self.tier2_atm_range, "tier2_expiry_count": self.tier2_expiry_count,
                "tier3_contracts": self.tier3_contracts,
            }
