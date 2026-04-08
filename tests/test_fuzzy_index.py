import pandas as pd
from src.search.fuzzy_index import FuzzyIndex

def _make_test_df():
    return pd.DataFrame([
        {"SEM_SMST_SECURITY_ID": 42528, "SM_SYMBOL_NAME": "NIFTY",
         "SEM_TRADING_SYMBOL": "NIFTY-24APR2026-23500-CE",
         "SEM_CUSTOM_SYMBOL": "NIFTY 24 APR 23500 CE",
         "SEM_STRIKE_PRICE": 23500, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_EXM_EXCH_ID": "NSE",
         "SEM_EXCH_INSTRUMENT_TYPE": "OPTIDX", "SEM_LOT_UNITS": 25},
        {"SEM_SMST_SECURITY_ID": 50001, "SM_SYMBOL_NAME": "RELIANCE",
         "SEM_TRADING_SYMBOL": "RELIANCE-24APR2026-2800-CE",
         "SEM_CUSTOM_SYMBOL": "RELIANCE 24 APR 2800 CE",
         "SEM_STRIKE_PRICE": 2800, "SEM_OPTION_TYPE": "CE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_EXM_EXCH_ID": "NSE",
         "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK", "SEM_LOT_UNITS": 250},
        {"SEM_SMST_SECURITY_ID": 60001, "SM_SYMBOL_NAME": "RELIANCE",
         "SEM_TRADING_SYMBOL": "RELIANCE-24APR2026-2900-PE",
         "SEM_CUSTOM_SYMBOL": "RELIANCE 24 APR 2900 PE",
         "SEM_STRIKE_PRICE": 2900, "SEM_OPTION_TYPE": "PE",
         "SEM_EXPIRY_DATE": "2026-04-24", "SEM_EXM_EXCH_ID": "BSE",
         "SEM_EXCH_INSTRUMENT_TYPE": "OPTSTK", "SEM_LOT_UNITS": 250},
    ])

def test_build_and_search_exact():
    idx = FuzzyIndex()
    idx.build(_make_test_df())
    results = idx.search("NIFTY", limit=5)
    assert len(results) >= 1
    assert results[0]["symbol"] == "NIFTY"

def test_search_fuzzy():
    idx = FuzzyIndex()
    idx.build(_make_test_df())
    results = idx.search("RELIANC", limit=5)
    assert len(results) >= 1
    assert results[0]["symbol"] == "RELIANCE"

def test_search_returns_metadata():
    idx = FuzzyIndex()
    idx.build(_make_test_df())
    results = idx.search("NIFTY", limit=1)
    r = results[0]
    assert "security_id" in r
    assert "symbol" in r
    assert "trading_symbol" in r
    assert "score" in r

def test_search_limit():
    idx = FuzzyIndex()
    idx.build(_make_test_df())
    results = idx.search("RELIANCE", limit=1)
    assert len(results) == 1

def test_search_empty():
    idx = FuzzyIndex()
    idx.build(_make_test_df())
    results = idx.search("XYZNOTEXIST", limit=5)
    assert len(results) == 0 or results[0]["score"] < 50
