import pandas as pd
from datetime import date
from src.scrip.scrip_master import ScripMaster, ContractNotFoundError

def _make_test_df():
    return pd.DataFrame([
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 42528,
         "SEM_TRADING_SYMBOL": "NIFTY-24APR2026-23500-CE", "SEM_CUSTOM_SYMBOL": "NIFTY 24 APR 23500 CE",
         "SEM_INSTRUMENT_NAME": "OPTIDX", "SEM_STRIKE_PRICE": 23500.0, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 25, "SEM_EXCH_INSTRUMENT_TYPE": "OPTIDX",
         "SM_SYMBOL_NAME": "NIFTY", "SEM_UNDERLYING_SECURITY_ID": 13, "SEM_UNDERLYING_SYMBOL": "NIFTY", "ISIN": ""},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 42529,
         "SEM_TRADING_SYMBOL": "NIFTY-24APR2026-23500-PE", "SEM_CUSTOM_SYMBOL": "NIFTY 24 APR 23500 PE",
         "SEM_INSTRUMENT_NAME": "OPTIDX", "SEM_STRIKE_PRICE": 23500.0, "SEM_OPTION_TYPE": "PE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 25, "SEM_EXCH_INSTRUMENT_TYPE": "OPTIDX",
         "SM_SYMBOL_NAME": "NIFTY", "SEM_UNDERLYING_SECURITY_ID": 13, "SEM_UNDERLYING_SYMBOL": "NIFTY", "ISIN": ""},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 42534,
         "SEM_TRADING_SYMBOL": "NIFTY-24APR2026-FUT", "SEM_CUSTOM_SYMBOL": "NIFTY 24 APR FUT",
         "SEM_INSTRUMENT_NAME": "FUTIDX", "SEM_STRIKE_PRICE": 0.0, "SEM_OPTION_TYPE": "XX",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 25, "SEM_EXCH_INSTRUMENT_TYPE": "FUTIDX",
         "SM_SYMBOL_NAME": "NIFTY", "SEM_UNDERLYING_SECURITY_ID": 13, "SEM_UNDERLYING_SYMBOL": "NIFTY", "ISIN": ""},
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 50001,
         "SEM_TRADING_SYMBOL": "RELIANCE-24APR2026-2800-CE", "SEM_CUSTOM_SYMBOL": "RELIANCE 24 APR 2800 CE",
         "SEM_INSTRUMENT_NAME": "OPTSTK", "SEM_STRIKE_PRICE": 2800.0, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 250, "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK",
         "SM_SYMBOL_NAME": "RELIANCE", "SEM_UNDERLYING_SECURITY_ID": 500325, "SEM_UNDERLYING_SYMBOL": "RELIANCE", "ISIN": "INE002A01018"},
        {"SEM_EXM_EXCH_ID": "BSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 60001,
         "SEM_TRADING_SYMBOL": "RELIANCE-24APR2026-2800-CE", "SEM_CUSTOM_SYMBOL": "RELIANCE 24 APR 2800 CE",
         "SEM_INSTRUMENT_NAME": "OPTSTK", "SEM_STRIKE_PRICE": 2800.0, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 250, "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK",
         "SM_SYMBOL_NAME": "RELIANCE", "SEM_UNDERLYING_SECURITY_ID": 500326, "SEM_UNDERLYING_SYMBOL": "RELIANCE", "ISIN": "INE002A01018"},
    ])

def _setup_scrip_master():
    """Helper to create a ScripMaster with test data and proper initialization."""
    import threading
    sm = ScripMaster.__new__(ScripMaster)
    sm._lock = threading.Lock()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    df = _make_test_df()
    index, expiry_index, strike_index, cross_map = sm._build_index(df)
    sm._df = df
    sm._index = index
    sm._expiry_index = expiry_index
    sm._strike_index = strike_index
    sm._cross_map = cross_map
    return sm

def test_resolve_option():
    sm = _setup_scrip_master()
    meta = sm.resolve("NIFTY", date(2026, 4, 24), 23500.0, "CE")
    assert meta.security_id == "42528"
    assert meta.underlying_security_id == "13"
    assert meta.underlying_symbol == "NIFTY"
    assert meta.lot_size == 25
    assert meta.contract_type.value == "CE"

def test_resolve_future():
    sm = _setup_scrip_master()
    meta = sm.resolve("NIFTY", date(2026, 4, 24), None, "FUT")
    assert meta.security_id == "42534"
    assert meta.strike is None

def test_resolve_not_found():
    sm = _setup_scrip_master()
    try:
        sm.resolve("BANKNIFTY", date(2026, 4, 24), 50000.0, "CE")
        assert False, "Should have raised ContractNotFoundError"
    except ContractNotFoundError:
        pass

def test_get_expiries():
    sm = _setup_scrip_master()
    expiries = sm.get_expiries("NIFTY")
    assert date(2026, 4, 24) in expiries

def test_cross_listing_detection():
    sm = _setup_scrip_master()
    meta = sm.resolve("RELIANCE", date(2026, 4, 24), 2800.0, "CE")
    assert meta.cross_listed is True
    assert "NSE" in meta.exchanges
    assert "BSE" in meta.exchanges
    assert meta.peer_security_id == "60001"

def test_get_all_strikes():
    sm = _setup_scrip_master()
    strikes = sm.get_strikes("NIFTY", date(2026, 4, 24))
    assert 23500.0 in strikes

def test_mcx_optfut_not_classified_as_future():
    """MCX OPTFUT instruments should be classified as options, not futures."""
    import threading
    sm = ScripMaster.__new__(ScripMaster)
    sm._lock = threading.Lock()
    sm._underlying_map = {}
    df = pd.DataFrame([
        {"SEM_EXM_EXCH_ID": "MCX", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 70001,
         "SEM_TRADING_SYMBOL": "CRUDEOIL-28APR2026-5000-CE", "SEM_CUSTOM_SYMBOL": "CRUDEOIL 28 APR 5000 CE",
         "SEM_INSTRUMENT_NAME": "OPTFUT", "SEM_STRIKE_PRICE": 5000.0, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-28", "SEM_LOT_UNITS": 100, "SEM_EXCH_INSTRUMENT_TYPE": "OPTFUT",
         "SM_SYMBOL_NAME": "CRUDEOIL", "SEM_UNDERLYING_SECURITY_ID": 999, "SEM_UNDERLYING_SYMBOL": "CRUDEOIL", "ISIN": ""},
    ])
    index, expiry_index, strike_index, cross_map = sm._build_index(df)
    # OPTFUT with CE option_type should be indexed as an option, not a future
    key = ("CRUDEOIL", date(2026, 4, 28), 5000.0, "CE", "MCX")
    assert key in index

def test_nan_security_id_skipped():
    """Rows with NaN security_id should be skipped."""
    import threading
    import math
    sm = ScripMaster.__new__(ScripMaster)
    sm._lock = threading.Lock()
    sm._underlying_map = {}
    df = pd.DataFrame([
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": float("nan"),
         "SEM_TRADING_SYMBOL": "BAD-24APR2026-100-CE", "SEM_CUSTOM_SYMBOL": "BAD",
         "SEM_INSTRUMENT_NAME": "OPTIDX", "SEM_STRIKE_PRICE": 100.0, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 25, "SEM_EXCH_INSTRUMENT_TYPE": "OPTIDX",
         "SM_SYMBOL_NAME": "BAD", "SEM_UNDERLYING_SECURITY_ID": 1, "SEM_UNDERLYING_SYMBOL": "BAD", "ISIN": ""},
    ])
    index, expiry_index, strike_index, cross_map = sm._build_index(df)
    assert len(index) == 0

def test_float_strike_rounding():
    """Strike prices with floating point imprecision should be rounded to 2dp."""
    import threading
    sm = ScripMaster.__new__(ScripMaster)
    sm._lock = threading.Lock()
    sm._underlying_map = {"TEST": "1"}
    df = pd.DataFrame([
        {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": 80001,
         "SEM_TRADING_SYMBOL": "TEST-24APR2026-100.15-CE", "SEM_CUSTOM_SYMBOL": "TEST 24 APR 100.15 CE",
         "SEM_INSTRUMENT_NAME": "OPTIDX", "SEM_STRIKE_PRICE": 100.14999999999999, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_LOT_UNITS": 25, "SEM_EXCH_INSTRUMENT_TYPE": "OPTIDX",
         "SM_SYMBOL_NAME": "TEST", "SEM_UNDERLYING_SECURITY_ID": 1, "SEM_UNDERLYING_SYMBOL": "TEST", "ISIN": ""},
    ])
    index, expiry_index, strike_index, cross_map = sm._build_index(df)
    sm._df = df
    sm._index = index
    sm._expiry_index = expiry_index
    sm._strike_index = strike_index
    sm._cross_map = cross_map
    # Should be able to resolve with the rounded strike
    meta = sm.resolve("TEST", date(2026, 4, 24), 100.15, "CE")
    assert meta.security_id == "80001"
    assert meta.strike == 100.15
