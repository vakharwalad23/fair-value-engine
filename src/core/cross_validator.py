"""Cross-validates engine Greeks/IV against Dhan option chain data."""
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Deviation:
    engine_value: Optional[float]
    dhan_value: Optional[float]
    absolute: Optional[float] = None
    pct: Optional[float] = None
    status: str = "N/A"  # OK, WARN, ALERT, N/A

    def __post_init__(self):
        if self.engine_value is not None and self.dhan_value is not None:
            self.absolute = round(self.engine_value - self.dhan_value, 6)
            if abs(self.dhan_value) > 1e-6:
                self.pct = round(abs(self.absolute / self.dhan_value) * 100, 2)
            else:
                self.pct = 0.0
            if self.pct < 5:
                self.status = "OK"
            elif self.pct < 15:
                self.status = "WARN"
            else:
                self.status = "ALERT"


@dataclass
class ValidationReport:
    security_id: str
    symbol: str
    iv: Deviation = field(default_factory=lambda: Deviation(None, None))
    delta: Deviation = field(default_factory=lambda: Deviation(None, None))
    theta: Deviation = field(default_factory=lambda: Deviation(None, None))
    gamma: Deviation = field(default_factory=lambda: Deviation(None, None))
    vega: Deviation = field(default_factory=lambda: Deviation(None, None))

    @property
    def has_alerts(self) -> bool:
        return any(d.status == "ALERT" for d in [self.iv, self.delta, self.theta, self.gamma, self.vega])

    @property
    def has_warnings(self) -> bool:
        return any(d.status == "WARN" for d in [self.iv, self.delta, self.theta, self.gamma, self.vega])

    def to_dict(self) -> dict:
        def dev_dict(d: Deviation) -> dict:
            return {"engine": d.engine_value, "dhan": d.dhan_value, "deviation": d.absolute, "pct": d.pct, "status": d.status}
        return {
            "security_id": self.security_id,
            "symbol": self.symbol,
            "iv": dev_dict(self.iv),
            "delta": dev_dict(self.delta),
            "theta": dev_dict(self.theta),
            "gamma": dev_dict(self.gamma),
            "vega": dev_dict(self.vega),
            "has_alerts": self.has_alerts,
            "has_warnings": self.has_warnings,
        }


class CrossValidator:
    """Compares engine FairResult against Dhan option chain data."""

    @staticmethod
    def validate(engine_result, chain_strike_data: dict) -> ValidationReport:
        """
        engine_result: FairResult from engine
        chain_strike_data: Dhan's per-strike data dict with keys like 'implied_volatility', 'greeks'
        """
        report = ValidationReport(
            security_id=engine_result.security_id,
            symbol=engine_result.symbol,
        )

        dhan_iv = chain_strike_data.get("implied_volatility")
        engine_iv = engine_result.implied_volatility
        if engine_iv is not None:
            engine_iv = engine_iv / 100  # engine stores as percentage, Dhan as decimal
        report.iv = Deviation(engine_iv, dhan_iv)

        greeks = chain_strike_data.get("greeks", {})
        report.delta = Deviation(engine_result.delta, greeks.get("delta"))
        report.theta = Deviation(engine_result.theta, greeks.get("theta"))
        report.gamma = Deviation(engine_result.gamma, greeks.get("gamma"))
        report.vega = Deviation(engine_result.vega, greeks.get("vega"))

        return report
