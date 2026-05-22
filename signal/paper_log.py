"""
paper_log.py — Ghi và theo dõi paper trades

paper_trades.csv columns:
  opened_at, signal, prob, entry, tp, sl, rr, est_minutes,
  order_type, closed_at, outcome, pnl_pct, hit_tp, hit_sl
"""

import csv
import sys
from pathlib import Path
from datetime import timezone, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PAPER_TRADES_FILE, KLINES_FILE

OUTCOME_WINDOW = timedelta(minutes=3)   # cửa sổ đánh giá TP/SL sau khi vào lệnh
FILL_WINDOW    = timedelta(seconds=30)  # maker order: fill check window

PAPER_COLS = [
    "opened_at", "signal", "prob", "entry", "tp", "sl", "rr", "est_minutes",
    "order_type",
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
        "opened_at":   opened_at.isoformat(),
        "signal":      signal["signal"],
        "prob":        signal["prob"],
        "entry":       signal["entry"],
        "tp":          signal["tp"],
        "sl":          signal["sl"],
        "rr":          signal["rr"],
        "est_minutes": signal.get("est_minutes", ""),
        "order_type":  signal.get("order_type", "market"),
        "closed_at":   "",
        "outcome":     "",
        "pnl_pct":     "",
        "hit_tp":      "",
        "hit_sl":      "",
    }
    with open(PAPER_TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=PAPER_COLS, extrasaction="ignore").writerow(row)
    print(
        f"[SIG] 📝 Paper trade ghi nhận | "
        f"entry={signal['entry']} TP={signal['tp']} SL={signal['sl']} R:R={signal['rr']}"
    )


def check_outcomes() -> int:
    """
    Điền outcome cho các trade đã đủ 3 phút (OUTCOME_WINDOW).
    Duyệt klines_1s.csv theo thứ tự thời gian:
      high >= tp → WIN (hit TP)
      low  <= sl → LOSS (hit SL)
      hết 3 phút không hit → EXPIRED

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
            continue  # chưa đủ OUTCOME_WINDOW (3 phút)

        entry      = float(trade["entry"])
        tp         = float(trade["tp"])
        sl         = float(trade["sl"])
        order_type = trade.get("order_type", "market")
        is_long    = trade.get("signal", "CASCADE_LONG") != "CASCADE_SHORT"

        # Load klines chỉ trong cửa sổ [opened_at, t_end]
        try:
            klines = pd.read_csv(
                KLINES_FILE,
                dtype={"high": float, "low": float, "close": float},
                usecols=["open_time", "high", "low", "close"],
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

        # Maker order: kiểm tra fill trong 30s đầu
        if order_type == "maker":
            fill_end     = opened_at + FILL_WINDOW
            fill_window  = window[window["open_time"] <= fill_end]
            filled       = False
            fill_time    = None
            for _, r in fill_window.iterrows():
                if is_long and r["low"] <= entry:
                    filled, fill_time = True, r["open_time"]
                    break
                if not is_long and r["high"] >= entry:
                    filled, fill_time = True, r["open_time"]
                    break

            if not filled:
                df.at[idx, "closed_at"] = (opened_at + FILL_WINDOW).isoformat()
                df.at[idx, "outcome"]   = "UNFILLED"
                df.at[idx, "pnl_pct"]   = 0.0
                df.at[idx, "hit_tp"]    = 0
                df.at[idx, "hit_sl"]    = 0
                print(f"[SIG] ⭕ UNFILLED | entry={entry} não chạm trong 30s")
                updated += 1
                continue

            # Filled — chỉ check TP/SL từ lúc fill trở đi
            window = window[window["open_time"] >= fill_time]

        # Duyệt từng nến 1s để xác định hit TP hay SL trước
        hit_tp = hit_sl = False
        close_price = entry

        for _, row in window.iterrows():
            if is_long:
                if row["high"] >= tp:
                    hit_tp = True
                    break
                if row["low"] <= sl:
                    hit_sl = True
                    break
            else:
                if row["low"] <= tp:
                    hit_tp = True
                    break
                if row["high"] >= sl:
                    hit_sl = True
                    break
            close_price = float(row["close"]) if "close" in row else float(row["low"])
        else:
            # Không hit → dùng giá cuối cùng trong cửa sổ
            close_price = float(window.iloc[-1]["low"])

        if hit_tp:
            outcome   = "WIN"
            pnl_pct   = round(abs(tp - entry) / entry * 100, 3)
            closed_at = opened_at + OUTCOME_WINDOW
        elif hit_sl:
            outcome   = "LOSS"
            pnl_pct   = round(-abs(sl - entry) / entry * 100, 3)
            closed_at = opened_at + OUTCOME_WINDOW
        else:
            outcome   = "EXPIRED"
            pnl_pct   = round((close_price - entry) / entry * 100 * (1 if is_long else -1), 3)
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


def has_open_trade(direction: str) -> bool:
    """Trả về True nếu đang có paper trade chưa resolved theo direction."""
    _init_file()
    try:
        df = pd.read_csv(PAPER_TRADES_FILE, dtype=str, keep_default_na=False)
        pending = df[df["outcome"] == ""]
        sig_name = "CASCADE_LONG" if direction == "long" else "CASCADE_SHORT"
        return any(pending["signal"] == sig_name)
    except Exception:
        return False


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
