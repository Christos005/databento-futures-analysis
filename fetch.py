"""
Download daily OHLCV bars for CME futures from the Databento Historical API.

Steps:
  1. Load the API key from the environment (or a local .env file).
  2. Ask Databento what the request will cost BEFORE downloading.
  3. Stop if the cost is above a safety limit (default $1.00).
  4. Download the data and save it to data/ as CSV, so the analysis
     can be re-run without paying for the same data twice.

Usage:
  python fetch.py                     # default: last 365 days, ES/NQ/CL/GC
  python fetch.py --start 2025-01-01 --end 2025-12-31
  python fetch.py --symbols ES.v.0 NQ.v.0 --max-cost 0.50
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import databento as db
except ImportError:
    sys.exit("The 'databento' package is not installed. Run: pip install -r requirements.txt")

try:
    from dotenv import load_dotenv

    load_dotenv()  # reads DATABENTO_API_KEY from a .env file if present
except ImportError:
    pass  # python-dotenv is optional; an exported environment variable works too

DATASET = "GLBX.MDP3"  # CME Globex MDP 3.0
SCHEMA = "ohlcv-1d"  # one open/high/low/close/volume bar per day
STYPE_IN = "continuous"
# ES.v.0 = the ES contract with the most trading volume the previous day.
# The volume roll rule (.v.) follows where the market actually trades. The calendar
# rule (.c.) follows the nearest expiry, which for gold and crude is often a thin,
# barely traded contract month.

DEFAULT_SYMBOLS = {
    "ES.v.0": "E-mini S&P 500",
    "NQ.v.0": "E-mini Nasdaq-100",
    "CL.v.0": "WTI Crude Oil",
    "GC.v.0": "Gold",
}

DATA_DIR = Path(__file__).parent / "data"


def parse_args() -> argparse.Namespace:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS), help="Continuous symbols, e.g. ES.v.0")
    parser.add_argument("--start", default=str(yesterday - timedelta(days=365)), help="Start date (inclusive), YYYY-MM-DD")
    parser.add_argument("--end", default=str(yesterday), help="End date (exclusive), YYYY-MM-DD")
    parser.add_argument("--max-cost", type=float, default=1.00, help="Abort if the estimated cost (USD) is above this")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    return parser.parse_args()


def get_client() -> "db.Historical":
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        sys.exit(
            "No API key found.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Paste your key from the Databento portal (API keys page) after DATABENTO_API_KEY=\n"
            "  Keys start with 'db-'. Never commit .env to GitHub."
        )
    if not key.startswith("db-"):
        print("Warning: Databento API keys normally start with 'db-'. Check you copied the whole key.")
    return db.Historical(key)


def main() -> None:
    args = parse_args()
    client = get_client()

    request = dict(
        dataset=DATASET,
        symbols=args.symbols,
        stype_in=STYPE_IN,
        schema=SCHEMA,
        start=args.start,
        end=args.end,
    )

    # 1. Check the cost first. This call is free.
    try:
        cost = client.metadata.get_cost(**request)
    except db.BentoClientError as err:
        sys.exit(f"Databento rejected the request (check the key, symbols and dates):\n  {err}")
    except db.BentoServerError as err:
        sys.exit(f"Databento server error, try again in a minute:\n  {err}")

    print(f"Request: {', '.join(args.symbols)} | {SCHEMA} | {args.start} -> {args.end}")
    print(f"Estimated cost: ${cost:.4f} (deducted from your free credits first)")

    if cost > args.max_cost:
        sys.exit(f"Stopped: cost is above the --max-cost limit of ${args.max_cost:.2f}. Narrow the dates or symbols.")
    if not args.yes and input("Download? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    # 2. Download.
    try:
        data = client.timeseries.get_range(**request)
    except db.BentoClientError as err:
        sys.exit(f"Download rejected:\n  {err}")
    except db.BentoServerError as err:
        sys.exit(f"Databento server error, try again in a minute:\n  {err}")

    df = data.to_df()  # prices as floats, symbols mapped, UTC timestamps
    if df.empty:
        sys.exit("The request returned no rows. Check the symbols and that the dates include trading days.")

    # 3. Save. The raw DBN file is Databento's own compact format; the CSV is for the analysis.
    DATA_DIR.mkdir(exist_ok=True)
    stem = f"{DATASET}_{SCHEMA}_{args.start}_{args.end}"
    data.to_file(DATA_DIR / f"{stem}.dbn.zst")
    cols = ["symbol", "instrument_id", "open", "high", "low", "close", "volume"]
    df[cols].to_csv(DATA_DIR / f"{stem}.csv")
    print(f"Saved {len(df):,} rows to data/{stem}.csv")
    print("Next: python analyze.py")


if __name__ == "__main__":
    main()
