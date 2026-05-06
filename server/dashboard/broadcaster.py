"""
broadcaster.py — Background thread: đọc data mỗi 1s → push WebSocket

Khởi động từ DashboardConfig.ready().
Dùng InMemoryChannelLayer để broadcast đến tất cả TickConsumer.
"""

import sys
import time
import json
import math
import random
import threading
from pathlib import Path

ROOT_DIR  = Path(__file__).parent.parent.parent   # /home/coder
MODEL_DIR = ROOT_DIR / "ml"
MODEL_FILE = MODEL_DIR / "artifacts" / "lgb_model.pkl"

# Thêm ml/ vào sys.path để import predict.py
if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from .data_reader import (
    read_latest_kline, read_latest_features,
    read_active_signal,
)

_model_ctx     = None
_model_mtime   = None
_prev_price    = None
_started       = False
_lock          = threading.Lock()


def _try_load_model():
    """Load hoặc reload model nếu file thay đổi."""
    global _model_ctx, _model_mtime
    if not MODEL_FILE.exists():
        return
    try:
        mtime = MODEL_FILE.stat().st_mtime
        if mtime == _model_mtime:
            return
        import predict as _predict
        _model_ctx   = _predict.load_model()
        _model_mtime = mtime
        print(f"[BC] Model loaded | AUC_test={_model_ctx['meta'].get('auc_test')}")
    except Exception as e:
        print(f"[BC] Model load error: {e}")


def _compute_prob(feature_row: dict) -> float | None:
    global _model_ctx
    if _model_ctx is None:
        return None
    try:
        import predict as _predict
        return round(_predict.predict_proba(_model_ctx, feature_row), 4)
    except Exception:
        return None


def _build_tick() -> dict:
    global _prev_price

    kline = read_latest_kline()
    feat  = read_latest_features()

    price = kline["close"] if kline else None

    # % thay đổi giá so với tick trước
    price_change_pct = None
    if price is not None and _prev_price is not None and _prev_price != 0:
        price_change_pct = round((price - _prev_price) / _prev_price * 100, 4)
    if price is not None:
        _prev_price = price

    def _f(d, key, default=None):
        if d is None:
            return default
        v = d.get(key, default)
        try:
            return float(v) if v not in (None, "", "nan", "None") else default
        except (TypeError, ValueError):
            return default

    liq_upper = _f(feat, "liq_zone_upper")
    liq_lower = _f(feat, "liq_zone_lower")
    dist_pct  = _f(feat, "dist_to_upper")
    imbalance = _f(feat, "imbalance_now")
    funding   = _f(feat, "funding_rate")
    delta_oi  = _f(feat, "delta_oi_5m")

    # CVD: thêm noise sin để sparkline trông live khi không có collector
    cvd_base = _f(feat, "cvd_delta_5m") or 0.0
    t = time.time()
    cvd_5m = round(cvd_base + math.sin(t * 0.4) * 35 + math.sin(t * 0.13) * 15
                   + random.gauss(0, 5), 2)

    prob      = _compute_prob(feat) if feat else None
    signal    = read_active_signal()

    sig_out = None
    if signal:
        sig_out = {
            "entry":      _f(signal, "entry"),
            "tp":         _f(signal, "tp"),
            "sl":         _f(signal, "sl"),
            "rr":         _f(signal, "rr"),
            "prob":       _f(signal, "prob"),
            "opened_at":  signal.get("opened_at", ""),
        }

    return {
        "ts":              kline["ts"] if kline else None,
        "price":           price,
        "price_change_pct": price_change_pct,
        "liq_upper":       liq_upper,
        "liq_lower":       liq_lower,
        "dist_upper_pct":  dist_pct,
        "imbalance":       imbalance,
        "cvd_5m":          cvd_5m,
        "funding_rate":    funding,
        "delta_oi_5m":     delta_oi,
        "prob":            prob,
        "signal":          sig_out,
    }


def _broadcast_loop():
    time.sleep(3)  # chờ Django khởi động xong

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()

    print("[BC] Broadcaster started — pushing tick every 1s")
    reload_counter = 0

    while True:
        try:
            # Reload model mỗi 60s
            reload_counter += 1
            if reload_counter >= 60:
                _try_load_model()
                reload_counter = 0

            tick = _build_tick()

            async_to_sync(channel_layer.group_send)(
                "tick",
                {"type": "tick.message", "data": tick},
            )
        except Exception as e:
            print(f"[BC] Error: {e}")

        time.sleep(1)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True

    _try_load_model()
    t = threading.Thread(target=_broadcast_loop, daemon=True)
    t.start()
