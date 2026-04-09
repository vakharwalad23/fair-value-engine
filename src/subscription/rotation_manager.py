"""ATM rotation manager: subscribes/unsubscribes contracts as spot moves."""
import logging
import time
import threading
from typing import Optional

from src.core.fair_engine import FairEngine
from src.core.models import ContractMeta, ContractType, Tick
from src.feed.connection_pool import ConnectionPool
from src.scrip.scrip_master import ScripMaster
from src.subscription.slot_tracker import SlotTracker
from src.subscription.tier_config import TierConfig

logger = logging.getLogger(__name__)

# Segment name for index underlyings (Dhan feed protocol)
_IDX_I = "IDX_I"
# Segment name for equity underlyings
_NSE_EQ = "NSE_EQ"

# Index symbols that use IDX_I segment
_INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})


class RotationManager:
    """Manages ATM-centred strike rotation for Tier 1 and Tier 2 underlyings.

    Tier 1 underlyings (indices): all available strikes are always subscribed.
    Tier 2 stocks: only ATM ± N strikes from the nearest two expiries.
    Tier 3: manually configured one-off contracts restored from TierConfig.

    When spot price moves far enough that the current ATM bucket shifts,
    on_spot_tick triggers _check_rotation which subscribes newly in-range
    strikes and marks out-of-range ones as stale.  Stale contracts that have
    exceeded stale_ttl seconds are unsubscribed and deregistered.
    """

    def __init__(
        self,
        engine: FairEngine,
        pool: ConnectionPool,
        scrip_master: ScripMaster,
        slot_tracker: SlotTracker,
        tier_config: TierConfig,
        stale_ttl: int = 1800,
    ):
        self._engine = engine
        self._pool = pool
        self._scrip_master = scrip_master
        self._slot_tracker = slot_tracker
        self._tier_config = tier_config
        self._stale_ttl = stale_ttl

        # security_id -> epoch time when it was marked stale
        self._stale: dict[str, float] = {}

        # underlying_symbol -> last known ATM strike (used to detect shift)
        self._last_atm: dict[str, float] = {}

        self._lock = threading.Lock()

    # Public methods

    def apply_tier1(self) -> None:
        """Subscribe all strikes across nearest expiries for each Tier 1 underlying."""
        for symbol in self._tier_config.tier1_underlyings:
            expiries = self._scrip_master.get_expiries(symbol)
            if not expiries:
                logger.warning(f"No expiries found for Tier 1 symbol {symbol}")
                continue
            for expiry in expiries[:self._tier_config.tier1_expiry_count]:
                chain = self._scrip_master.get_chain(symbol, expiry)
                for meta in chain:
                    meta.tier = 1
                    self._subscribe_contract(meta)
            # Subscribe the underlying instrument so the engine receives spot ticks
            underlying_sid = self._scrip_master.get_underlying_security_id(symbol)
            if underlying_sid:
                seg = self._resolve_underlying_segment_for_symbol(symbol)
                self._pool.subscribe(underlying_sid, seg)
                self._slot_tracker.add(underlying_sid, tier=1)

    def apply_tier2(self) -> None:
        """Subscribe ATM ± N strikes for each Tier 2 stock across nearest expiries."""
        for symbol in self._tier_config.tier2_stocks:
            expiries = self._scrip_master.get_expiries(symbol)
            if not expiries:
                logger.warning(f"No expiries found for Tier 2 symbol {symbol}")
                continue
            # No spot yet — subscribe full chain; rotation will narrow it later
            for expiry in expiries[:self._tier_config.tier2_expiry_count]:
                chain = self._scrip_master.get_chain(symbol, expiry)
                for meta in chain:
                    meta.tier = 2
                    self._subscribe_contract(meta)
            # Subscribe the underlying instrument so the engine receives spot ticks
            underlying_sid = self._scrip_master.get_underlying_security_id(symbol)
            if underlying_sid:
                seg = self._resolve_underlying_segment_for_symbol(symbol)
                self._pool.subscribe(underlying_sid, seg)
                self._slot_tracker.add(underlying_sid, tier=2)

    def restore_tier3(self) -> None:
        """Re-subscribe Tier 3 manual one-offs from TierConfig."""
        subscribed_underlyings: set[str] = set()
        for entry in self._tier_config.tier3_contracts:
            sid = entry.get("security_id")
            seg = entry.get("exchange_segment")
            if not sid or not seg:
                logger.warning(f"Skipping malformed Tier 3 entry: {entry}")
                continue
            # Build a minimal stub meta for slot tracking purposes; engine
            # registration is skipped for Tier 3 entries that lack full metadata.
            self._pool.subscribe(sid, seg)
            self._slot_tracker.add(sid, 3)
            # Ensure the underlying is also subscribed
            underlying_symbol = entry.get("underlying_symbol")
            if underlying_symbol and underlying_symbol not in subscribed_underlyings:
                underlying_sid = self._scrip_master.get_underlying_security_id(underlying_symbol)
                if underlying_sid:
                    u_seg = self._resolve_underlying_segment_for_symbol(underlying_symbol)
                    self._pool.subscribe(underlying_sid, u_seg)
                    self._slot_tracker.add(underlying_sid, tier=3)
                    subscribed_underlyings.add(underlying_symbol)

    def on_spot_tick(self, tick: Tick) -> None:
        """Called for every underlying spot price tick.

        Looks up the underlying symbol from the engine's registered contracts
        and triggers rotation if the ATM bucket has shifted.
        """
        # Identify the symbol associated with this underlying security_id.
        symbol = self._engine.find_underlying_symbol(tick.security_id)

        if symbol is None:
            return

        self._check_rotation(symbol, tick.ltp)

    def _check_rotation(self, symbol: str, spot: float) -> None:
        """Rotate subscriptions if ATM has shifted for the given symbol."""
        if symbol in self._tier_config.tier1_underlyings:
            return  # Tier 1 is always-on, no rotation
        expiries = self._scrip_master.get_expiries(symbol)
        if not expiries:
            return

        n = self._tier_config.tier2_atm_range

        for expiry in expiries[:self._tier_config.tier2_expiry_count]:
            strikes = self._scrip_master.get_strikes(symbol, expiry)
            if not strikes:
                continue

            new_atm = self._nearest_strike(spot, strikes)
            cache_key = f"{symbol}:{expiry}"

            with self._lock:
                old_atm = self._last_atm.get(cache_key)
                if old_atm == new_atm:
                    continue
                self._last_atm[cache_key] = new_atm

            in_range = set(self._strikes_in_range(new_atm, strikes, n))

            # Subscribe newly in-range contracts
            for strike in in_range:
                for ct in ("CE", "PE"):
                    try:
                        meta = self._scrip_master.resolve(symbol, expiry, strike, ct)
                        meta.tier = 2
                        self._subscribe_contract(meta)
                    except Exception:
                        pass

            # Mark out-of-range contracts stale
            for strike in strikes:
                if strike not in in_range:
                    for ct in ("CE", "PE"):
                        try:
                            meta = self._scrip_master.resolve(symbol, expiry, strike, ct)
                            self._mark_stale(meta.security_id)
                        except Exception:
                            pass

        # Evict any expired stale contracts
        self._evict_expired_stale()

    def _subscribe_contract(self, meta: ContractMeta) -> None:
        """Register with engine, subscribe via pool, and track slot usage."""
        self._engine.register_contract(meta)
        seg = meta.exchange_segment
        ok = self._pool.subscribe(meta.security_id, seg)
        if ok:
            tier = meta.tier if meta.tier is not None else 2
            self._slot_tracker.add(meta.security_id, tier)
            # Remove from stale if it was previously marked
            with self._lock:
                self._stale.pop(meta.security_id, None)
        else:
            logger.warning(f"Pool refused subscription for {meta.security_id} ({meta.symbol})")

    def _resolve_underlying_segment(self, meta: ContractMeta) -> str:
        """Return IDX_I for index underlyings, NSE_EQ for stocks."""
        if meta.underlying_symbol in _INDEX_SYMBOLS:
            return _IDX_I
        return _NSE_EQ

    @staticmethod
    def _resolve_underlying_segment_for_symbol(symbol: str) -> str:
        """Return IDX_I for known index symbols, NSE_EQ for stocks."""
        if symbol in _INDEX_SYMBOLS:
            return _IDX_I
        return _NSE_EQ

    def _mark_stale(self, security_id: str) -> None:
        """Record the time at which a contract became stale."""
        with self._lock:
            if security_id not in self._stale:
                self._stale[security_id] = time.time()

    def _evict_expired_stale(self) -> list[str]:
        """Unsubscribe and deregister contracts that have been stale beyond TTL.

        Returns the list of security_ids that were evicted.
        """
        now = time.time()
        evicted: list[str] = []

        with self._lock:
            expired = [
                sid for sid, ts in self._stale.items()
                if now - ts >= self._stale_ttl
            ]
            for sid in expired:
                del self._stale[sid]

        for sid in expired:
            meta = self._engine.get_contract(sid)
            if meta is None:
                continue
            # Never evict Tier 1 contracts
            if meta.tier == 1:
                continue
            self._pool.unsubscribe(sid, meta.exchange_segment)
            self._engine.deregister_contract(sid)
            self._slot_tracker.remove(sid)
            evicted.append(sid)
            logger.debug(f"Evicted stale contract {sid}")

        return evicted

    @staticmethod
    def _nearest_strike(spot: float, strikes: list) -> float:
        """Return the strike closest to spot price."""
        return min(strikes, key=lambda k: abs(k - spot))

    @staticmethod
    def _strikes_in_range(atm: float, strikes: list, n: int) -> list:
        """Return strikes within n steps of atm (inclusive on both sides).

        Steps are counted by sorted position in the strikes list.
        """
        sorted_strikes = sorted(strikes)
        try:
            idx = sorted_strikes.index(atm)
        except ValueError:
            # atm not in list; find nearest index
            diffs = [abs(s - atm) for s in sorted_strikes]
            idx = diffs.index(min(diffs))
        lo = max(0, idx - n)
        hi = min(len(sorted_strikes) - 1, idx + n)
        return sorted_strikes[lo:hi + 1]
