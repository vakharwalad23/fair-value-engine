"""Scrip master CSV download, cache, and contract resolution."""
import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.core.models import ContractMeta, ContractType
from src.utils.time_utils import next_refresh_delay_seconds

logger = logging.getLogger(__name__)

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

EXCHANGE_SEGMENT_MAP = {
    ("NSE", "OPTIDX"): "NSE_FNO", ("NSE", "FUTIDX"): "NSE_FNO",
    ("NSE", "OPTSTK"): "NSE_FNO", ("NSE", "FUTSTK"): "NSE_FNO",
    ("BSE", "OPTIDX"): "BSE_FNO", ("BSE", "FUTIDX"): "BSE_FNO",
    ("BSE", "OPTSTK"): "BSE_FNO", ("BSE", "FUTSTK"): "BSE_FNO",
    ("MCX", "OPTFUT"): "MCX_COMM", ("MCX", "FUTCOM"): "MCX_COMM",
    ("NSE", "OPTCUR"): "NSE_CURRENCY", ("NSE", "FUTCUR"): "NSE_CURRENCY",
}

OPTION_TYPE_MAP = {"CE": ContractType.CALL, "PE": ContractType.PUT}


class ContractNotFoundError(Exception):
    pass


class AmbiguousContractError(Exception):
    pass


class ScripMaster:
    def __init__(self, cache_dir: str = "cache"):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path = self._cache_dir / "scrip_master.csv"
        self._df: Optional[pd.DataFrame] = None
        self._index: dict = {}
        self._expiry_index: dict = {}
        self._strike_index: dict = {}
        self._cross_map: dict = {}
        self._refresh_timer: Optional[threading.Timer] = None

    def load(self):
        self._download_if_stale()
        self._df = pd.read_csv(self._cache_path, low_memory=False)
        fno_types = {"OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK", "OPTFUT", "FUTCOM", "OPTCUR", "FUTCUR"}
        self._df = self._df[self._df["SEM_EXCH_INSTRUMENT_TYPE"].isin(fno_types)].copy()
        self._df["SEM_EXPIRY_DATE"] = pd.to_datetime(self._df["SEM_EXPIRY_DATE"]).dt.date
        self._df["SEM_STRIKE_PRICE"] = pd.to_numeric(self._df["SEM_STRIKE_PRICE"], errors="coerce").fillna(0)
        self._build_index()
        logger.info(f"Scrip master loaded: {len(self._df)} F&O instruments")

    def _download_if_stale(self):
        if self._cache_path.exists():
            age_hours = (datetime.now().timestamp() - self._cache_path.stat().st_mtime) / 3600
            if age_hours < 24:
                logger.info(f"Using cached scrip master ({age_hours:.1f}h old)")
                return
        logger.info("Downloading scrip master CSV...")
        import requests
        resp = requests.get(SCRIP_MASTER_URL, timeout=60)
        resp.raise_for_status()
        self._cache_path.write_bytes(resp.content)
        logger.info(f"Scrip master downloaded: {len(resp.content) / 1024 / 1024:.1f} MB")

    def _build_index(self):
        self._index = {}
        self._expiry_index = {}
        self._strike_index = {}
        self._cross_map = {}

        for _, row in self._df.iterrows():
            symbol = row["SM_SYMBOL_NAME"]
            raw_expiry = row["SEM_EXPIRY_DATE"]
            if isinstance(raw_expiry, str):
                expiry = datetime.strptime(raw_expiry, "%Y-%m-%d").date()
            else:
                expiry = raw_expiry
            strike = float(row["SEM_STRIKE_PRICE"])
            opt_type = row["SEM_OPTION_TYPE"]
            exch = row["SEM_EXM_EXCH_ID"]
            inst_type = row["SEM_EXCH_INSTRUMENT_TYPE"]
            sec_id = str(int(row["SEM_SMST_SECURITY_ID"]))

            if "FUT" in inst_type:
                ct_key = "FUT"
                strike_key = None
            else:
                ct_key = opt_type
                strike_key = strike

            key = (symbol, expiry, strike_key, ct_key, exch)
            self._index[key] = row

            self._expiry_index.setdefault(symbol, set()).add(expiry)

            if strike_key is not None:
                self._strike_index.setdefault((symbol, expiry), set()).add(strike_key)

            isin = str(row.get("ISIN", "")).strip()
            if isin and isin != "nan":
                self._cross_map.setdefault(isin, []).append({
                    "security_id": sec_id, "exchange": exch, "key": key,
                })

    def resolve(self, symbol: str, expiry: date, strike: Optional[float], contract_type: str) -> ContractMeta:
        strike_key = None if contract_type == "FUT" else strike

        row = None
        resolved_exch = None
        for exch in ("NSE", "BSE", "MCX"):
            key = (symbol, expiry, strike_key, contract_type, exch)
            if key in self._index:
                row = self._index[key]
                resolved_exch = exch
                break

        if row is None:
            raise ContractNotFoundError(f"No contract found: {symbol} {expiry} strike={strike} type={contract_type}")

        sec_id = str(int(row["SEM_SMST_SECURITY_ID"]))
        inst_type = row["SEM_EXCH_INSTRUMENT_TYPE"]
        exch_segment = EXCHANGE_SEGMENT_MAP.get((resolved_exch, inst_type), f"{resolved_exch}_FNO")
        ct = OPTION_TYPE_MAP.get(contract_type, ContractType.FUTURE)

        isin = str(row.get("ISIN", "")).strip()
        cross_listed = False
        exchanges = [resolved_exch]
        peer_security_id = None
        if isin and isin != "nan" and isin in self._cross_map:
            peers = self._cross_map[isin]
            other_exchanges = [p for p in peers if p["exchange"] != resolved_exch]
            if other_exchanges:
                cross_listed = True
                exchanges = sorted(set(p["exchange"] for p in peers))
                peer_security_id = other_exchanges[0]["security_id"]

        return ContractMeta(
            security_id=sec_id,
            symbol=str(row.get("SEM_CUSTOM_SYMBOL", row["SEM_TRADING_SYMBOL"])),
            contract_type=ct, strike=strike_key, expiry=expiry,
            underlying_security_id=str(int(row["SEM_UNDERLYING_SECURITY_ID"])),
            underlying_symbol=str(row["SEM_UNDERLYING_SYMBOL"]),
            exchange_segment=exch_segment,
            lot_size=int(row.get("SEM_LOT_UNITS", 1)),
            cross_listed=cross_listed, exchanges=exchanges, peer_security_id=peer_security_id,
        )

    def get_expiries(self, symbol: str) -> list[date]:
        return sorted(self._expiry_index.get(symbol, set()))

    def get_strikes(self, symbol: str, expiry: date) -> list[float]:
        return sorted(self._strike_index.get((symbol, expiry), set()))

    def get_chain(self, symbol: str, expiry: date) -> list[ContractMeta]:
        results = []
        for ct in ("CE", "PE", "FUT"):
            if ct == "FUT":
                try:
                    results.append(self.resolve(symbol, expiry, None, ct))
                except ContractNotFoundError:
                    pass
            else:
                for strike in self.get_strikes(symbol, expiry):
                    try:
                        results.append(self.resolve(symbol, expiry, strike, ct))
                    except ContractNotFoundError:
                        pass
        return results

    @property
    def dataframe(self) -> pd.DataFrame:
        return self._df

    def schedule_daily_refresh(self):
        delay = next_refresh_delay_seconds(8, 45)
        logger.info(f"Next scrip master refresh in {delay / 3600:.1f}h")
        self._refresh_timer = threading.Timer(delay, self._daily_refresh)
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _daily_refresh(self):
        try:
            if self._cache_path.exists():
                self._cache_path.unlink()
            self.load()
            logger.info("Scrip master refreshed successfully")
        except Exception as e:
            logger.error(f"Scrip master refresh failed: {e}")
        self.schedule_daily_refresh()

    def stop(self):
        if self._refresh_timer:
            self._refresh_timer.cancel()
