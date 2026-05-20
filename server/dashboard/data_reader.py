"""
data_reader.py — Đọc CSV files → Python dicts
"""

import sys
from pathlib import Path
from datetime import timezone, timedelta

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
from config import (
    KLINES_FILE, LIQ_FILE, FEATURES_FILE,
    PAPER_TRADES_FILE as TRADES_FILE,
    SYMBOL,
)

KLINE_COLS = ["open_time", "open", "high", "low", "close",
              "volume", "taker_buy_vol", "num_trades"]
LIQ_COLS   = ["event_time", "symbol", "side", "price", "qty", "usd_value"]


# ── Fast tail read ─────────────────────────────────────────────

def _tail_lines(filepath: Path, n: int = 10) -> list[str]:
    if not filepath.exists():
        return []
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size  = f.tell()
            chunk = min(size, 4096)
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")
        lines = [l for l in raw.splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


def read_latest_kline() -> dict | None:
    lines = _tail_lines(KLINES_FILE, 5)
    for line in reversed(lines):
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            return {
                "ts":     parts[0],
                "open":   float(parts[1]),
                "high":   float(parts[2]),
                "low":    float(parts[3]),
                "close":  float(parts[4]),
                "volume": float(parts[5]),
            }
        except ValueError:
            continue
    return None


def read_latest_features() -> dict | None:
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
    if not TRADES_FILE.exists():
        return None
    try:
        df = pd.read_csv(TRADES_FILE, dtype=str, keep_default_na=False)
        pending = df[df["outcome"] == ""]
        if pending.empty:
            return None
        latest    = pending.iloc[-1].to_dict()
        opened_at = pd.to_datetime(latest.get("opened_at"), utc=True, errors="coerce")
        if pd.isna(opened_at):
            return None
        if pd.Timestamp.now(tz="UTC") - opened_at > timedelta(minutes=30):
            return None
        return latest
    except Exception:
        return None


# ── Full load (REST views) ────────────────────────────────────

def load_klines_chart(hours: int = 0) -> list[dict]:
    if not KLINES_FILE.exists():
        return []
    try:
        df = pd.read_csv(
            KLINES_FILE,
            names=KLINE_COLS, header=0,
            dtype={"open": float, "high": float, "low": float,
                   "close": float, "volume": float},
            usecols=["open_time", "open", "high", "low", "close", "volume"],
        )
        df["open_time"] = pd.to_datetime(df["open_time"], format="ISO8601", utc=True, errors="coerce")
        df = df.dropna(subset=["open_time"]).sort_values("open_time")

        if hours > 0:
            since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
            df = df[df["open_time"] >= since]

        if df.empty:
            return []

        span_hours = (df["open_time"].iloc[-1] - df["open_time"].iloc[0]).total_seconds() / 3600
        tf = "1min" if span_hours < 6 else ("5min" if span_hours <= 72 else "15min")

        df_agg = df.resample(tf, on="open_time").agg(
            open=("open", "first"), high=("high", "max"),
            low=("low", "min"), close=("close", "last"),
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
                "tf":     tf,
            }
            for _, row in df_agg.iterrows()
        ]
    except Exception as e:
        print(f"[DR] load_klines_chart error: {e}")
        return []


def load_liquidations(hours: int = 0) -> list[dict]:
    if not LIQ_FILE.exists():
        return []
    try:
        df = pd.read_csv(
            LIQ_FILE,
            names=LIQ_COLS, header=0,
            dtype={"price": float, "qty": float, "usd_value": float},
        )
        df["event_time"] = pd.to_datetime(df["event_time"], format="ISO8601", utc=True, errors="coerce")
        df = df.dropna(subset=["event_time"])
        df = df[df["symbol"] == SYMBOL]
        if hours > 0:
            since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
            df = df[df["event_time"] >= since]
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
    if not TRADES_FILE.exists():
        return []
    try:
        df = pd.read_csv(TRADES_FILE, dtype=str)
        return df.tail(limit).fillna("").iloc[::-1].to_dict(orient="records")
    except Exception:
        return []


def load_signal_state() -> dict:
    feat   = read_latest_features()
    signal = read_active_signal()

    def _f(key, default=None):
        if feat is None:
            return default
        v = feat.get(key, default)
        try:
            return float(v) if v not in (None, "", "nan", "None") else default
        except (TypeError, ValueError):
            return default

    return {
        "current_price": _f("current_price"),
        "imbalance":     _f("imbalance_now"),
        "cvd_1m":        _f("cvd_delta_1m"),
        "funding_rate":  _f("funding_rate"),
        "delta_oi_1m":   _f("delta_oi_1m"),
        "feature_ts":    feat.get("timestamp") if feat else None,
        "active_signal": _sig(signal),
    }


def _sig(signal: dict | None) -> dict | None:
    if signal is None:
        return None
    def _to_f(v):
        try:
            return float(v) if v not in (None, "", "nan", "None") else None
        except (TypeError, ValueError):
            return None
    return {
        "signal":      signal.get("signal", ""),
        "entry":       _to_f(signal.get("entry")),
        "tp":          _to_f(signal.get("tp")),
        "sl":          _to_f(signal.get("sl")),
        "rr":          _to_f(signal.get("rr")),
        "prob":        _to_f(signal.get("prob")),
        "est_minutes": _to_f(signal.get("est_minutes")),
        "opened_at":   signal.get("opened_at", ""),
    }
