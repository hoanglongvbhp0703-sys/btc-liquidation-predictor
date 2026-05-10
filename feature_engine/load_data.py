"""
load_data.py — Đọc và parse tất cả CSV files

Cấu trúc thực tế của từng file (xác nhận từ dữ liệu thật):

klines_1s.csv:
  open_time, open, high, low, close, volume, taker_buy_vol, num_trades
  2026-05-04T03:51:00+00:00,80184.60,80206.80,80184.50,80206.80,24.625,17.283,606

liquidations.csv:
  event_time, symbol, side, price, qty, usd_value
  2026-05-04T03:51:26+00:00,1000PEPEUSDT,BUY,0.0040836,71343,291.3362748

open_interest.csv:
  timestamp, oi_btc, oi_usd
  2026-05-04T03:51:36+00:00,108012.996,8664446096.23320

funding_rate.csv:
  timestamp, funding_rate, next_funding_time
  2026-05-04T03:50:39+00:00,0.00005127,2026-05-04T08:00:00+00:00

orderbook.csv:
  timestamp,
  bid1_price,bid1_qty, bid2_price,bid2_qty, bid3_price,bid3_qty,
  bid4_price,bid4_qty, bid5_price,bid5_qty,
  ask1_price,ask1_qty, ask2_price,ask2_qty, ask3_price,ask3_qty,
  ask4_price,ask4_qty, ask5_price,ask5_qty,
  mid_price, spread, bid_vol_total, ask_vol_total, imbalance
  2026-05-04T03:51:20+00:00,80206.70,7.013,...,80206.75,0.10,7.182,1.723,0.8065

aggtrades.csv:
  timestamp, agg_id, price, qty, usd_value, is_buyer_maker, cvd_delta
  2026-05-04T03:51:23+00:00,3276342312,80206.80,0.747,59914.47960,False,0.747
"""

import sys
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_DIR


def _parse_dt(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Parse cột datetime an toàn với mọi dạng ISO8601.
    errors='coerce' để drop các row bị lỗi (ví dụ: header row lẫn vào data).
    """
    df[col] = pd.to_datetime(df[col], format="ISO8601", utc=True, errors="coerce")
    df = df.dropna(subset=[col]).reset_index(drop=True)
    return df


def load_klines(since=None) -> pd.DataFrame:
    """
    Columns: open_time, open, high, low, close, volume, taker_buy_vol, num_trades
    """
    df = pd.read_csv(
        DATA_DIR / "klines_1s.csv",
        names=["open_time", "open", "high", "low", "close",
               "volume", "taker_buy_vol", "num_trades"],
        header=0,
        dtype={"open": float, "high": float, "low": float, "close": float,
               "volume": float, "taker_buy_vol": float, "num_trades": int},
    )
    df = _parse_dt(df, "open_time")
    if since is not None:
        df = df[df["open_time"] >= since]
    return df.sort_values("open_time").reset_index(drop=True)


def load_liquidations(since=None) -> pd.DataFrame:
    """
    Columns: event_time, symbol, side, price, qty, usd_value
    side: BUY = SHORT bị quét, SELL = LONG bị quét
    """
    df = pd.read_csv(
        DATA_DIR / "liquidations.csv",
        names=["event_time", "symbol", "side", "price", "qty", "usd_value"],
        header=0,
        dtype={"price": float, "qty": float, "usd_value": float},
    )
    df = _parse_dt(df, "event_time")
    if since is not None:
        df = df[df["event_time"] >= since]
    return df.sort_values("event_time").reset_index(drop=True)


def load_orderbook(since=None) -> pd.DataFrame:
    """
    26 columns: timestamp + 10 bid/ask levels + 5 computed features
    """
    cols = [
        "timestamp",
        "bid1_price", "bid1_qty", "bid2_price", "bid2_qty",
        "bid3_price", "bid3_qty", "bid4_price", "bid4_qty",
        "bid5_price", "bid5_qty",
        "ask1_price", "ask1_qty", "ask2_price", "ask2_qty",
        "ask3_price", "ask3_qty", "ask4_price", "ask4_qty",
        "ask5_price", "ask5_qty",
        "mid_price", "spread", "bid_vol_total", "ask_vol_total", "imbalance",
    ]
    float_cols = [c for c in cols if c != "timestamp"]
    df = pd.read_csv(
        DATA_DIR / "orderbook.csv",
        names=cols, header=0,
        dtype={c: float for c in float_cols},
    )
    df = _parse_dt(df, "timestamp")
    if since is not None:
        df = df[df["timestamp"] >= since]
    return df.sort_values("timestamp").reset_index(drop=True)


def load_aggtrades(since=None) -> pd.DataFrame:
    """
    Columns: timestamp, agg_id, price, qty, usd_value, is_buyer_maker, cvd_delta
    agg_id = "BATCH" cho dòng tổng hợp 1s, số nguyên cho lệnh lớn riêng lẻ
    is_buyer_maker: True = bán CĐ, False = mua CĐ
    """
    df = pd.read_csv(
        DATA_DIR / "aggtrades.csv",
        names=["timestamp", "agg_id", "price", "qty",
               "usd_value", "is_buyer_maker", "cvd_delta"],
        header=0,
        dtype={"price": float, "qty": float, "usd_value": float, "cvd_delta": float},
    )
    df = _parse_dt(df, "timestamp")
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.strip().map(
        {"True": True, "False": False}
    )
    if since is not None:
        df = df[df["timestamp"] >= since]
    return df.sort_values("timestamp").reset_index(drop=True)


def load_open_interest(since=None) -> pd.DataFrame:
    """
    Columns: timestamp, oi_btc, oi_usd
    """
    df = pd.read_csv(
        DATA_DIR / "open_interest.csv",
        names=["timestamp", "oi_btc", "oi_usd"],
        header=0,
        dtype={"oi_btc": float, "oi_usd": float},
    )
    df = _parse_dt(df, "timestamp")
    if since is not None:
        df = df[df["timestamp"] >= since]
    return df.sort_values("timestamp").reset_index(drop=True)


def load_funding_rate(since=None) -> pd.DataFrame:
    """
    Columns: timestamp, funding_rate, next_funding_time
    """
    df = pd.read_csv(
        DATA_DIR / "funding_rate.csv",
        names=["timestamp", "funding_rate", "next_funding_time"],
        header=0,
        dtype={"funding_rate": float},
    )
    df = _parse_dt(df, "timestamp")
    df = _parse_dt(df, "next_funding_time")
    if since is not None:
        df = df[df["timestamp"] >= since]
    return df.sort_values("timestamp").reset_index(drop=True)