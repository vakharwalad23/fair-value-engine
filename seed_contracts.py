"""
seed_contracts.py
==================
Calls Dhan Option Chain API to fetch active NIFTY contracts,
registers them with FareEngine, and saves to contracts.json
for server auto-load on startup.

Usage:
    python seed_contracts.py --underlying NIFTY --expiry 2025-04-24
"""

import argparse
import json
import requests
import sys
from datetime import date, datetime

DHAN_API = "https://api.dhan.co/v2"

# Known underlying security IDs for indices
UNDERLYING_MAP = {
    "NIFTY":       {"id": "13",  "seg": "IDX_I"},
    "BANKNIFTY":   {"id": "25",  "seg": "IDX_I"},
    "FINNIFTY":    {"id": "27",  "seg": "IDX_I"},
    "MIDCPNIFTY":  {"id": "442", "seg": "IDX_I"},
    "SENSEX":      {"id": "1",   "seg": "IDX_I"},
}


def get_headers(client_id: str, access_token: str) -> dict:
    return {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
    }


def fetch_expiry_list(underlying: str, client_id: str, token: str) -> list:
    info = UNDERLYING_MAP[underlying]
    resp = requests.post(
        f"{DHAN_API}/optionchain/expirylist",
        headers=get_headers(client_id, token),
        json={"UnderlyingScrip": int(info["id"]), "UnderlyingSeg": info["seg"]},
    )
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_option_chain(underlying: str, expiry: str, client_id: str, token: str) -> dict:
    info = UNDERLYING_MAP[underlying]
    resp = requests.post(
        f"{DHAN_API}/optionchain",
        headers=get_headers(client_id, token),
        json={
            "UnderlyingScrip": int(info["id"]),
            "UnderlyingSeg": info["seg"],
            "Expiry": expiry,
        },
    )
    resp.raise_for_status()
    return resp.json()["data"]


def build_contracts(underlying: str, expiry: str, chain_data: dict, atm_range: int = 10) -> list:
    """
    Build contract metadata list from option chain response.
    Only includes ±atm_range strikes around ATM.
    """
    info = UNDERLYING_MAP[underlying]
    spot = chain_data["last_price"]
    strikes = sorted([float(k) for k in chain_data["oc"].keys()])

    # Find ATM index
    diffs = [abs(s - spot) for s in strikes]
    atm_idx = diffs.index(min(diffs))

    selected = strikes[max(0, atm_idx - atm_range): atm_idx + atm_range + 1]

    contracts = []

    for strike in selected:
        strike_data = chain_data["oc"].get(f"{strike:.6f}", {})
        for opt_type, key in [("CE", "ce"), ("PE", "pe")]:
            opt = strike_data.get(key)
            if not opt:
                continue
            contracts.append({
                "security_id": str(opt["security_id"]),
                "symbol": f"{underlying}{expiry.replace('-','')}{int(strike)}{opt_type}",
                "contract_type": opt_type,
                "strike": strike,
                "expiry": expiry,
                "underlying_security_id": info["id"],
                "underlying_symbol": underlying,
                "exchange_segment": "NSE_FNO",
                "lot_size": 25 if underlying == "NIFTY" else 15,
                "risk_free_rate": 0.065,
            })

    return contracts


def main():
    parser = argparse.ArgumentParser(description="Seed F&O contracts from Dhan Option Chain")
    parser.add_argument("--underlying", default="NIFTY", choices=list(UNDERLYING_MAP.keys()))
    parser.add_argument("--expiry", default=None, help="YYYY-MM-DD. Defaults to nearest expiry.")
    parser.add_argument("--atm-range", type=int, default=10, help="±N strikes around ATM")
    parser.add_argument("--client-id", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--out", default="contracts.json")
    args = parser.parse_args()

    # Try env if not provided
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    client_id = args.client_id or os.getenv("DHAN_CLIENT_ID", "")
    token     = args.token     or os.getenv("DHAN_ACCESS_TOKEN", "")

    if not client_id or not token:
        print("ERROR: Provide --client-id and --token, or set DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN env vars.")
        sys.exit(1)

    print(f"Fetching expiry list for {args.underlying}...")
    expiries = fetch_expiry_list(args.underlying, client_id, token)
    print(f"Available expiries: {expiries[:5]}...")

    expiry = args.expiry or expiries[0]
    if expiry not in expiries:
        print(f"ERROR: {expiry} not in available expiries.")
        sys.exit(1)

    print(f"Fetching option chain for {args.underlying} expiry={expiry}...")
    chain_data = fetch_option_chain(args.underlying, expiry, client_id, token)
    spot = chain_data["last_price"]
    print(f"Spot: {spot}")

    contracts = build_contracts(args.underlying, expiry, chain_data, args.atm_range)
    print(f"Built {len(contracts)} contracts (±{args.atm_range} strikes)")

    with open(args.out, "w") as f:
        json.dump(contracts, f, indent=2)

    print(f"Saved to {args.out}")
    print("\nNext: python load_contracts.py  OR  start server with auto-load")


if __name__ == "__main__":
    main()
