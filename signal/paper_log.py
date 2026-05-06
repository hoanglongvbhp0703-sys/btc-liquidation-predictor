"""
paper_log.py — Ghi và theo dõi paper trades

paper_trades.csv columns:
  opened_at, signal, prob, entry, tp, sl, rr,
  closed_at, outcome, pnl_pct, hit_tp, hit_sl
"""

import csv
from pathlib import Path
from datetime import timezone, timedelta

import pandas as pd

BASE_DIR          = Path(__file__).parent.parent
PAPER_TRADES_FILE = BASE_DIR / "data" / "processed" / "paper_trades.csv"
KLINES_FILE       = BASE_DIR / "data" / "raw"       / "klines_1s.csv"

OUTCOME_WINDOW = timedelta(minutes=30)

PAPER_COLS = [
    "opened_at", "signal", "prob", "entry", "tp", "sl", "rr",
    "closed_at", "outcome", "pnl_pct", "hit_tp", "hit_sl",
]


def _init_file():
    if not PAPER_TRADES_FILE.exists():
        with open(PAPER_TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(PAPER_COLS)


def log_signal(signal: dict, opened_at: pd.Timestamp) -> None:
    """Ghi 1 signal mới vào paper_trades.csv (chưa có outcome)."""
    _init_file()
    row = {
        "opened_at": opened_at.isoformat(),
        "signal":    signal["signal"],
        "prob":      signal["prob"],
        "entry":     signal["entry"],
        "tp":        signal["tp"],
        "sl":        signal["sl"],
        "rr":        signal["rr"],
        "closed_at": "",
        "outcome":   "",
        "pnl_pct":   "",
        "hit_tp":    "",
        "hit_sl":    "",
    }
    with open(PAPER_TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=PAPER_COLS, extrasaction="ignore").writerow(row)
    print(
        f"[SIG] 📝 Paper trade ghi nhận | "
        f"entry={signal['entry']} TP={signal['tp']} SL={signal['sl']} R:R={signal['rr']}"
    )


def check_outcomes() -> int:
    """
    Điền outcome cho các trade đã đủ 30 phút.
    Duyệt klines_1s.csv theo thứ tự thời gian:
      high >= tp → WIN (hit TP)
      low  <= sl → LOSS (hit SL)
      hết 30 phút không hit → EXPIRED

    Returns: số trade vừa được update.
    """
    _init_file()
    df = pd.read_csv(PAPER_TRADES_FILE, dtype=str, keep_default_na=False)
    if df.empty:
        return 0

    pending = df[df["outcome"] == ""].copy()
    if pending.empty:
        return 0

    now = pd.Timestamp.now(tz="UTC")
    updated = 0

    for idx, trade in pending.iterrows():
        opened_at = pd.to_datetime(trade["opened_at"], utc=True, errors="coerce")
        if pd.isna(opened_at):
            continue

        t_end = opened_at + OUTCOME_WINDOW
        if now < t_end:
            continue  # chưa đủ 30 phút

        entry = float(trade["entry"])
        tp    = float(trade["tp"])
        sl    = float(trade["sl"])

        # Load klines chỉ trong cửa sổ [opened_at, t_end]
        try:
            klines = pd.read_csv(
                KLINES_FILE,
                names=["open_time", "open", "high", "low", "close",
                       "volume", "taker_buy_vol", "num_trades"],
                header=None,
                dtype={"high": float, "low": float},
                usecols=["open_time", "high", "low"],
            )
            klines["open_time"] = pd.to_datetime(
                klines["open_time"], format="ISO8601", utc=True, errors="coerce"
            )
            klines = klines.dropna(subset=["open_time"])
            window = klines[
                (klines["open_time"] >= opened_at) & (klines["open_time"] <= t_end)
            ].sort_values("open_time")
        except Exception:
            continue

        if window.empty:
            continue

        # Duyệt từng nến 1s để xác định hit TP hay SL trước
        hit_tp = hit_sl = False
        close_price = entry

        for _, row in window.iterrows():
            if row["high"] >= tp:
                hit_tp = True
                break
            if row["low"] <= sl:
                hit_sl = True
                break
            close_price = row["low"] if row["low"] < entry else row["high"]
        else:
            # Không hit → dùng giá cuối cùng trong cửa sổ
            close_price = float(window.iloc[-1]["low"])

        if hit_tp:
            outcome  = "WIN"
            pnl_pct  = round((tp - entry) / entry * 100, 3)
            closed_at = opened_at + OUTCOME_WINDOW
        elif hit_sl:
            outcome  = "LOSS"
            pnl_pct  = round((sl - entry) / entry * 100, 3)
            closed_at = opened_at + OUTCOME_WINDOW
        else:
            outcome   = "EXPIRED"
            pnl_pct   = round((close_price - entry) / entry * 100, 3)
            closed_at = t_end

        df.at[idx, "closed_at"] = closed_at.isoformat()
        df.at[idx, "outcome"]   = outcome
        df.at[idx, "pnl_pct"]   = pnl_pct
        df.at[idx, "hit_tp"]    = int(hit_tp)
        df.at[idx, "hit_sl"]    = int(hit_sl)

        icon = "✅" if outcome == "WIN" else ("❌" if outcome == "LOSS" else "⏳")
        print(
            f"[SIG] {icon} Trade closed | "
            f"outcome={outcome} pnl={pnl_pct:+.2f}% | "
            f"opened={opened_at.strftime('%H:%M')}"
        )
        updated += 1

    if updated > 0:
        df.to_csv(PAPER_TRADES_FILE, index=False)

    return updated


def print_stats() -> None:
    """In thống kê paper trading ra stdout."""
    _init_file()
    df = pd.read_csv(PAPER_TRADES_FILE, dtype=str)
    closed = df[df["outcome"].isin(["WIN", "LOSS", "EXPIRED"])]

    total  = len(closed)
    wins   = (closed["outcome"] == "WIN").sum()
    losses = (closed["outcome"] == "LOSS").sum()
    exp    = (closed["outcome"] == "EXPIRED").sum()

    win_rate = wins / total * 100 if total > 0 else 0.0

    try:
        pnl_vals = pd.to_numeric(closed["pnl_pct"], errors="coerce").dropna()
        total_pnl = pnl_vals.sum()
        avg_pnl   = pnl_vals.mean()
    except Exception:
        total_pnl = avg_pnl = 0.0

    print("\n── Paper Trading Stats ───────────────────────")
    print(f"  Tổng trades   : {total}  (pending: {len(df) - total})")
    print(f"  WIN           : {wins}  ({win_rate:.1f}%)")
    print(f"  LOSS          : {losses}")
    print(f"  EXPIRED       : {exp}")
    print(f"  Total PnL     : {total_pnl:+.2f}%")
    print(f"  Avg PnL/trade : {avg_pnl:+.2f}%")
    print("──────────────────────────────────────────────\n")
