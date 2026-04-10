from src.core.cross_validator import CrossValidator, Deviation, ValidationReport

def test_deviation_ok():
    d = Deviation(0.50, 0.51)
    assert d.status == "OK"
    assert d.absolute is not None

def test_deviation_warn():
    # abs((0.50 - 0.55) / 0.55) * 100 = 9.09% -> WARN
    d = Deviation(0.50, 0.55)
    assert d.status == "WARN"

def test_deviation_alert():
    d = Deviation(0.50, 1.0)
    assert d.status == "ALERT"

def test_deviation_none():
    d = Deviation(None, 0.5)
    assert d.status == "N/A"

def test_validation_report_to_dict():
    r = ValidationReport(security_id="42528", symbol="NIFTY23500CE")
    r.iv = Deviation(0.15, 0.155)
    d = r.to_dict()
    assert "iv" in d
    assert d["security_id"] == "42528"
    assert d["iv"]["status"] == "OK"

def test_validate_with_chain_data():
    from dataclasses import dataclass
    @dataclass
    class FakeResult:
        security_id: str = "42528"
        symbol: str = "NIFTY23500CE"
        implied_volatility: float = 15.0  # percentage
        delta: float = 0.54
        theta: float = -15.2
        gamma: float = 0.0013
        vega: float = 12.2

    chain_data = {
        "implied_volatility": 0.15,  # decimal
        "greeks": {"delta": 0.55, "theta": -15.0, "gamma": 0.0013, "vega": 12.0},
    }
    report = CrossValidator.validate(FakeResult(), chain_data)
    assert report.iv.status == "OK"
    assert report.delta.status == "OK"
    assert not report.has_alerts
