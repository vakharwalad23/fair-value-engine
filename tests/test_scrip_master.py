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

def test_resolve_option():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    meta = sm.resolve("NIFTY", date(2026, 4, 24), 23500.0, "CE")
    assert meta.security_id == "42528"
    assert meta.underlying_security_id == "13"
    assert meta.underlying_symbol == "NIFTY"
    assert meta.lot_size == 25
    assert meta.contract_type.value == "CE"

def test_resolve_future():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    meta = sm.resolve("NIFTY", date(2026, 4, 24), None, "FUT")
    assert meta.security_id == "42534"
    assert meta.strike is None

def test_resolve_not_found():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    try:
        sm.resolve("BANKNIFTY", date(2026, 4, 24), 50000.0, "CE")
        assert False, "Should have raised ContractNotFoundError"
    except ContractNotFoundError:
        pass

def test_get_expiries():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    expiries = sm.get_expiries("NIFTY")
    assert date(2026, 4, 24) in expiries

def test_cross_listing_detection():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    meta = sm.resolve("RELIANCE", date(2026, 4, 24), 2800.0, "CE")
    assert meta.cross_listed is True
    assert "NSE" in meta.exchanges
    assert "BSE" in meta.exchanges
    assert meta.peer_security_id == "60001"

def test_get_all_strikes():
    sm = ScripMaster.__new__(ScripMaster)
    sm._df = _make_test_df()
    sm._underlying_map = {"NIFTY": "13", "RELIANCE": "500325"}
    sm._build_index()
    strikes = sm.get_strikes("NIFTY", date(2026, 4, 24))
    assert 23500.0 in strikes
