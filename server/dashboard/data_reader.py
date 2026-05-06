"""
data_reader.py — Đọc CSV files → Python dicts

Hai nhóm hàm:
  - Fast (tail): dùng trong broadcaster (gọi mỗi 1s)
  - Full load:   dùng trong REST views (gọi theo request)
"""

import sys
from pathlib import Path
from datetime import timezone, timedelta

import pandas as pd

# Thêm root vào sys.path để import model/predict nếu cần
ROOT_DIR      = Path(__file__).parent.parent.parent   # /home/coder
RAW_DIR       = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

KLINES_FILE   = RAW_DIR       / "klines_1s.csv"
LIQ_FILE      = RAW_DIR       / "liquidations.csv"
OB_FILE       = RAW_DIR       / "orderbook.csv"
FEATURES_FILE = PROCESSED_DIR / "features_5m.csv"
TRADES_FILE   = PROCESSED_DIR / "paper_trades.csv"

KLINE_COLS = ["open_time", "open", "high", "low", "close",
              "volume", "taker_buy_vol", "num_trades"]
LIQ_COLS   = ["event_time", "symbol", "side", "price", "qty", "usd_value"]


# ── Fast tail read (không load toàn bộ file) ────────────────────

def _tail_lines(filepath: Path, n: int = 10) -> list[str]:
    """Đọc n dòng cuối của file mà không load toàn bộ."""
    if not filepath.exists():
        return []
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 4096)
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")
        lines = [l for l in raw.splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


def read_latest_kline() -> dict | None:
    """Đọc nến 1s mới nhất. Rất nhanh — không load toàn file."""
    lines = _tail_lines(KLINES_FILE, 5)
    for line in reversed(lines):
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            return {
                "ts":    parts[0],
                "open":  float(parts[1]),
                "high":  float(parts[2]),
                "low":   float(parts[3]),
                "close": float(parts[4]),
                "volume": float(parts[5]),
            }
        except ValueError:
            continue
    return None


def read_latest_features() -> dict | None:
    """Đọc feature row mới nhất từ features_5m.csv (có header)."""
    if not FEATURES_FILE.exists():
        return None
    try:
        df = pd.read_csv(FEATURES_FILE, dtype=str)
        if df.empty:
            return None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df.iloc[-1].to_dict()
    except Exception:
        return None


def read_active_signal() -> dict | None:
    """Đọc paper trade gần nhất chưa đóng (outcome trống, mở trong 30p)."""
    if not TRADES_FILE.exists():
        return None
    try:
        df = pd.read_csv(TRADES_FILE, dtype=str, keep_default_na=False)
        pending = df[df["outcome"] == ""]
        if pending.empty:
            return None
        latest = pending.iloc[-1].to_dict()
        opened_at = pd.to_datetime(latest.get("opened_at"), utc=True, errors="coerce")
        if pd.isna(opened_at):
            return None
        now = pd.Timestamp.now(tz="UTC")
        if now - opened_at > timedelta(minutes=30):
            return None  # đã quá 30 phút, outcome chưa điền
        return latest
    except Exception:
        return None


# ── Full load (REST views) ────────────────────────────────────────

def load_klines_chart(hours: int = 2) -> list[dict]:
    """
    Đọc klines_1s, aggregate thành 1m candles cho chart.
    Trả về list[dict] với keys: ts, open, high, low, close, volume.
    """
    if not KLINES_FILE.exists():
        return []
    try:
        since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
        df = pd.read_csv(
            KLINES_FILE,
            names=KLINE_COLS, header=0,
            dtype={"open": float, "high": float, "low": float,
                   "close": float, "volume": float},
            usecols=["open_time", "open", "high", "low", "close", "volume"],
        )
        df["open_time"] = pd.to_datetime(df["open_time"], format="ISO8601", utc=True, errors="coerce")
        df = df.dropna(subset=["open_time"])
        df = df[df["open_time"] >= since].sort_values("open_time")

        if df.empty:
            return []

        df_1m = df.resample("1min", on="open_time").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna().reset_index()

        return [
            {
                "ts":     row["open_time"].isoformat(),
                "open":   round(row["open"], 2),
                "high":   round(row["high"], 2),
                "low":    round(row["low"], 2),
                "close":  round(row["close"], 2),
                "volume": round(row["volume"], 3),
            }
            for _, row in df_1m.iterrows()
        ]
    except Exception as e:
        print(f"[DR] load_klines_chart error: {e}")
        return []


def load_liquidations(hours: int = 4) -> list[dict]:
    """Đọc liquidations trong N giờ gần nhất."""
    if not LIQ_FILE.exists():
        return []
    try:
        since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
        df = pd.read_csv(
            LIQ_FILE,
            names=LIQ_COLS, header=0,
            dtype={"price": float, "qty": float, "usd_value": float},
        )
        df["event_time"] = pd.to_datetime(df["event_time"], format="ISO8601", utc=True, errors="coerce")
        df = df.dropna(subset=["event_time"])
        df = df[(df["event_time"] >= since) & (df["symbol"] == "BTCUSDT")]
        df = df.sort_values("event_time")
        return [
            {
                "ts":        row["event_time"].isoformat(),
                "side":      row["side"],
                "price":     round(row["price"], 2),
                "usd_value": round(row["usd_value"], 0),
            }
            for _, row in df.iterrows()
        ]
    except Exception as e:
        print(f"[DR] load_liquidations error: {e}")
        return []


def load_trades(limit: int = 30) -> list[dict]:
    """Đọc paper trades gần nhất."""
    if not TRADES_FILE.exists():
        return []
    try:
        df = pd.read_csv(TRADES_FILE, dtype=str)
        df = df.tail(limit).fillna("").iloc[::-1]
        return df.to_dict(orient="records")
    except Exception:
        return []


def load_signal_state() -> dict:
    """Trả về state đầy đủ cho /api/signal/."""
    feat    = read_latest_features()
    signal  = read_active_signal()

    def _f(key, default=None):
        if feat is None:
            return default
        v = feat.get(key, default)
        try:
            return float(v) if v not in (None, "", "nan", "None") else default
        except (TypeError, ValueError):
            return default

    return {
        "current_price":  _f("current_price"),
        "liq_upper":      _f("liq_zone_upper"),
        "liq_lower":      _f("liq_zone_lower"),
        "dist_upper_pct": _f("dist_to_upper"),
        "imbalance":      _f("imbalance_now"),
        "cvd_5m":         _f("cvd_delta_5m"),
        "funding_rate":   _f("funding_rate"),
        "delta_oi_5m":    _f("delta_oi_5m"),
        "feature_ts":     feat.get("timestamp") if feat else None,
        "active_signal":  _sig(signal),
    }


def _sig(signal: dict | None) -> dict | None:
    """Convert active signal string fields → float cho API response."""
    if signal is None:
        return None
    def _to_f(v):
        try:
            return float(v) if v not in (None, "", "nan", "None") else None
        except (TypeError, ValueError):
            return None
    return {
        "entry":     _to_f(signal.get("entry")),
        "tp":        _to_f(signal.get("tp")),
        "sl":        _to_f(signal.get("sl")),
        "rr":        _to_f(signal.get("rr")),
        "prob":      _to_f(signal.get("prob")),
        "opened_at": signal.get("opened_at", ""),
    }
