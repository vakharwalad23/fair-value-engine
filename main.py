"""Entrypoint — starts FastAPI/uvicorn with snapshot logging."""
import argparse
import logging

import uvicorn

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="F&O Fair Engine")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--interval", type=float, default=30.0, help="Snapshot log interval (seconds)")
    args = parser.parse_args()

    from server import engine, app
    from src.core.models import FairResult

    def snapshot_log(results: list[FairResult]):
        signals = [r for r in results if r.signal != "FAIR"]
        print(f"\n[Snapshot] {len(results)} contracts | {len(signals)} signals")
        if signals:
            for r in sorted(signals, key=lambda r: -r.signal_strength)[:15]:
                print(
                    f"  {r.symbol:<25} {r.contract_type.value:>5} "
                    f"{str(r.strike or 'N/A'):>8} "
                    f"{r.market_price:>9.2f} {r.fair_value:>9.2f} "
                    f"{r.mispricing_pct:>+8.2f}% "
                    f"{r.signal}"
                )

    engine.on_snapshot(args.interval, snapshot_log)

    host = args.host
    print(f"Dashboard: http://{'localhost' if host == '0.0.0.0' else host}:{args.port}/")
    print(f"API docs:  http://{'localhost' if host == '0.0.0.0' else host}:{args.port}/docs")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
