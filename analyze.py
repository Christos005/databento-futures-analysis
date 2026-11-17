"""
Analyse the daily futures bars saved by fetch.py.

Outputs:
  charts/performance.png   growth of $100 in each market
  charts/volatility.png    20-day rolling volatility (annualised)
  charts/correlation.png   correlation of daily returns between markets
  charts/volume.png        average volume by weekday
  results/summary.md       key numbers, ready to paste into the README

Usage:
  python analyze.py                   # uses the newest CSV in data/
  python analyze.py --file data/xyz.csv
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save charts to files without needing a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR, CHART_DIR, RESULT_DIR = ROOT / "data", ROOT / "charts", ROOT / "results"

NAMES = {"ES": "E-mini S&P 500", "NQ": "E-mini Nasdaq-100", "CL": "WTI Crude Oil", "GC": "Gold"}
TRADING_DAYS = 252


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["ts_event"])
    df["date"] = df["ts_event"].dt.date
    # Daily bars are cut at midnight UTC. CME Globex reopens on Sunday evening (US time),
    # which is still Sunday in UTC, so each week starts with a short, thin "Sunday" bar.
    # Treating it as a full trading day would add ~52 fake days a year and create
    # spurious one-day moves. Weekend bars are dropped; Monday's bar covers that trading.
    weekday = pd.to_datetime(df["date"]).dt.day_of_week
    df = df[weekday < 5]
    df = df.sort_values("volume").drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    return df


def add_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Daily close-to-close returns, ignoring the day the continuous contract rolls.

    ES.v.0 always points at the most-traded contract. When it rolls to the next
    contract (instrument_id changes), the price can jump because the two contracts
    trade at different levels. That jump is not a real market move, so the return
    for a roll day is set to NaN instead of distorting the statistics.
    """
    df = df.copy()
    g = df.groupby("symbol")
    df["return"] = g["close"].pct_change()
    df["roll"] = g["instrument_id"].diff().fillna(0).ne(0)
    df.loc[df["roll"], "return"] = np.nan
    return df


def max_drawdown(returns: pd.Series) -> float:
    growth = (1 + returns.fillna(0)).cumprod()
    return float((growth / growth.cummax() - 1).min())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="CSV produced by fetch.py (default: newest in data/)")
    args = parser.parse_args()

    path = args.file or max(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, default=None)
    if path is None or not path.exists():
        sys.exit("No data found. Run: python fetch.py")

    df = add_returns(load(path))
    returns = df.pivot(index="date", columns="symbol", values="return")
    label = lambda s: f"{NAMES.get(s.split('.')[0], s)} ({s.split('.')[0]})"
    CHART_DIR.mkdir(exist_ok=True)
    RESULT_DIR.mkdir(exist_ok=True)

    # --- Chart 1: growth of $100 -------------------------------------------------
    growth = 100 * (1 + returns.fillna(0)).cumprod()
    fig, ax = plt.subplots(figsize=(10, 5))
    for s in growth:
        ax.plot(growth.index, growth[s], label=label(s), linewidth=1.6)
    ax.axhline(100, color="grey", linewidth=0.8, linestyle="--")
    ax.set(title="Growth of $100 (roll days excluded)", ylabel="Value ($)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "performance.png", dpi=150)

    # --- Chart 2: 20-day rolling volatility ----------------------------------------
    vol = returns.rolling(20, min_periods=15).std() * np.sqrt(TRADING_DAYS) * 100
    fig, ax = plt.subplots(figsize=(10, 5))
    for s in vol:
        ax.plot(vol.index, vol[s], label=label(s), linewidth=1.4)
    ax.set(title="20-day rolling volatility (annualised)", ylabel="Volatility (%)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "volatility.png", dpi=150)

    # --- Chart 3: correlation of daily returns --------------------------------------
    corr = returns.corr()
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), [s.split(".")[0] for s in corr.columns])
    ax.set_yticks(range(len(corr)), [s.split(".")[0] for s in corr.index])
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=10)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_title("Correlation of daily returns")
    fig.tight_layout()
    fig.savefig(CHART_DIR / "correlation.png", dpi=150)

    # --- Chart 4: average volume by weekday ---------------------------------------
    df["weekday"] = pd.to_datetime(df["date"]).dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    by_day = df[df["weekday"].isin(order)].groupby(["weekday", "symbol"])["volume"].mean().unstack()
    by_day = by_day.reindex(order) / by_day.reindex(order).mean()  # relative to each market's average
    fig, ax = plt.subplots(figsize=(10, 5))
    by_day.plot.bar(ax=ax, width=0.8)
    ax.axhline(1, color="grey", linewidth=0.8, linestyle="--")
    ax.set(title="Average volume by weekday (1.0 = market's average day)", xlabel="", ylabel="Relative volume")
    ax.legend([label(s) for s in by_day.columns], frameon=False)
    plt.xticks(rotation=0)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "volume.png", dpi=150)

    # --- Summary table -----------------------------------------------------------
    rows = []
    for s in returns:
        r = returns[s].dropna()
        sub = df[df["symbol"] == s]
        best, worst = r.idxmax(), r.idxmin()
        rows.append(
            {
                "Market": label(s),
                "Total return": f"{(growth[s].iloc[-1] / 100 - 1):+.1%}",
                "Annualised volatility": f"{r.std() * np.sqrt(TRADING_DAYS):.1%}",
                "Max drawdown": f"{max_drawdown(r):.1%}",
                "Best day": f"{r.max():+.2%} ({best})",
                "Worst day": f"{r.min():+.2%} ({worst})",
                "Avg daily volume": f"{sub['volume'].mean():,.0f}",
                "Contract rolls": int(sub["roll"].sum()),
            }
        )
    table = pd.DataFrame(rows)
    period = f"{df['date'].min()} to {df['date'].max()}"
    pairs = corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1)).stack()

    lines = [
        "# Results",
        "",
        f"Data: Databento `GLBX.MDP3`, `ohlcv-1d`, {period} ({returns.shape[0]} trading days).",
        "",
        "| " + " | ".join(table.columns) + " |",
        "|" + "---|" * len(table.columns),
        *("| " + " | ".join(map(str, row)) + " |" for row in table.itertuples(index=False)),
        "",
        f"- Most correlated pair: **{pairs.idxmax()[0]} / {pairs.idxmax()[1]}** ({pairs.max():.2f})",
        f"- Least correlated pair: **{pairs.idxmin()[0]} / {pairs.idxmin()[1]}** ({pairs.min():.2f})",
        f"- Busiest weekday overall: **{by_day.mean(axis=1).idxmax()}**; quietest: **{by_day.mean(axis=1).idxmin()}**",
        "",
    ]
    (RESULT_DIR / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print("Charts saved to charts/, summary saved to results/summary.md")


if __name__ == "__main__":
    main()
