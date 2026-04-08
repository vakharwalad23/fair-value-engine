"""
main.py — entrypoint
======================
1. Loads contracts from contracts.json (or generates demo ones)
2. Registers them with FareEngine
3. Starts FastAPI/uvicorn server

Usage:
    python main.py
    python main.py --contracts contracts.json --port 8000 --interval 30
"""

import argparse
import json
import logging
import sys
import os
from datetime import date

import uvicorn

logger = logging.getLogger(__name__)


def load_contracts_from_file(path: str, engine) -> int:
    from fare_engine import ContractMeta, ContractType
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return 0
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        return 0

    loaded = 0
    for item in data:
        try:
            ct = ContractType(item["contract_type"].upper())
            expiry = date.fromisoformat(item["expiry"])
            meta = ContractMeta(
                security_id=str(item["security_id"]),
                symbol=item["symbol"],
                contract_type=ct,
                strike=item.get("strike"),
                expiry=expiry,
                underlying_security_id=str(item["underlying_security_id"]),
                underlying_symbol=item["underlying_symbol"],
                exchange_segment=item.get("exchange_segment", "NSE_FNO"),
                lot_size=item.get("lot_size", 1),
                risk_free_rate=item.get("risk_free_rate", 0.065),
            )
            engine.register_contract(meta)
            loaded += 1
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping contract {item.get('symbol', '?')}: {e}")

    return loaded


def load_demo_contracts(engine):
    """Load fake NIFTY contracts for simulation/demo."""
    from fare_engine import ContractMeta, ContractType
    today = date.today()
    # Use a future Thursday as expiry
    from datetime import timedelta
    days_ahead = (3 - today.weekday()) % 7 or 7
    expiry = today + timedelta(days=days_ahead + 21)

    contracts = [
        ContractMeta("42528", "NIFTY23500CE", ContractType.CALL, 23500, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42529", "NIFTY23500PE", ContractType.PUT,  23500, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42530", "NIFTY23600CE", ContractType.CALL, 23600, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42531", "NIFTY23600PE", ContractType.PUT,  23600, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42532", "NIFTY23400CE", ContractType.CALL, 23400, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42533", "NIFTY23400PE", ContractType.PUT,  23400, expiry, "13", "NIFTY", "NSE_FNO"),
        ContractMeta("42534", "NIFTYFUT",     ContractType.FUTURE, None, expiry, "13", "NIFTY", "NSE_FNO"),
    ]
    for c in contracts:
        engine.register_contract(c)
    return len(contracts)


def main():
    parser = argparse.ArgumentParser(description="F&O Fare Engine")
    parser.add_argument("--contracts", default="contracts.json", help="Path to contracts JSON")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--interval", type=float, default=30.0, help="Snapshot log interval (seconds)")
    parser.add_argument("--demo", action="store_true", help="Force demo mode with simulated data")
    args = parser.parse_args()

    # Import engine from server (server.py owns the singleton)
    from server import engine, app

    # Register snapshot logging
    from fare_engine import FareResult
    from typing import List

    def snapshot_log(results: List[FareResult]):
        signals = [r for r in results if r.signal != "FAIR"]
        print(f"\n{'─'*60}")
        print(f"[Snapshot] {len(results)} contracts | {len(signals)} signals")
        if signals:
            print(f"{'Symbol':<25} {'Type':>5} {'Strike':>8} {'Mkt':>9} {'Fair':>9} {'Mis%':>8} {'Signal'}")
            print(f"{'─'*25} {'─'*5} {'─'*8} {'─'*9} {'─'*9} {'─'*8} {'─'*12}")
            for r in sorted(signals, key=lambda r: -r.signal_strength)[:15]:
                print(
                    f"{r.symbol:<25} {r.contract_type:>5} "
                    f"{str(r.strike or 'N/A'):>8} "
                    f"{r.market_price:>9.2f} {r.fair_value:>9.2f} "
                    f"{r.mispricing_pct:>+8.2f}% "
                    f"{r.signal}"
                )
        print(f"{'─'*60}\n")

    engine.on_snapshot(args.interval, snapshot_log)

    # Load contracts
    if not args.demo:
        loaded = load_contracts_from_file(args.contracts, engine)
        if loaded == 0:
            print(f"No contracts loaded from {args.contracts} — using demo contracts.")
            loaded = load_demo_contracts(engine)
    else:
        loaded = load_demo_contracts(engine)

    print(f"✓ {loaded} contracts registered")
    print(f"✓ Dashboard: http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/")
    print(f"✓ API docs:  http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/docs")
    print(f"✓ Snapshot interval: {args.interval}s")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
