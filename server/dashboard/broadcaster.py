"""
broadcaster.py — Background thread: đọc data mỗi 1s → push WebSocket

Tick payload:
  price, price_change_pct, ts
  imbalance, cvd_5m, funding_rate, delta_oi_5m
  cascade_prob_long, cascade_prob_short    — P(cascade trong 30m)
  cascade_curve_long, cascade_curve_short  — {5→p, ..., 30→p}
  time_to_cascade_long, time_to_cascade_short — ước tính phút
  cascade_signal_long, cascade_signal_short   — signal dict | None
"""

import sys
import time
import threading
from pathlib import Path

ROOT_DIR  = Path(__file__).parent.parent.parent
MODEL_DIR = ROOT_DIR / "ml"
MODEL_FILE = MODEL_DIR / "artifacts" / "lgb_cascade_long_3m.pkl"

if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from .data_reader import read_latest_kline, read_latest_features, read_active_signal

_model_ctx   = None
_model_mtime = None
_prev_price  = None
_started     = False
_lock        = threading.Lock()


def _current_model_mtime() -> float | None:
    return MODEL_FILE.stat().st_mtime if MODEL_FILE.exists() else None


def _try_load_model():
    global _model_ctx, _model_mtime
    if not MODEL_FILE.exists():
        return
    try:
        mtime = _current_model_mtime()
        if mtime == _model_mtime:
            return
        import predict as _predict
        _model_ctx   = _predict.load_model()
        _model_mtime = mtime
        avg_auc = _model_ctx["meta"].get("avg_auc_test", "N/A")
        print(f"[BC] Model loaded | avg_auc={avg_auc}")
    except Exception as e:
        print(f"[BC] Model load error: {e}")


def _predict_cascade(feature_row: dict, direction: str) -> tuple[float | None, dict, float | None]:
    """Returns (prob_30m, curve_dict, time_to_cascade)."""
    if _model_ctx is None:
        return None, {}, None
    try:
        import predict as _predict
        prob  = _predict.predict_cascade_prob(_model_ctx, feature_row, direction)
        curve = _predict.predict_cascade_curve(_model_ctx, feature_row, direction)
        ttc   = _predict.predict_time_to_cascade(_model_ctx, feature_row, direction)
        return prob, curve, ttc
    except Exception:
        return None, {}, None


def _predict_signal(feature_row: dict, price: float) -> dict | None:
    if _model_ctx is None or price is None:
        return None
    try:
        import predict as _predict
        return _predict.predict_cascade_signal(_model_ctx, feature_row, price)
    except Exception:
        return None


def _sig_dict(signal: dict | None) -> dict | None:
    if signal is None:
        return None
    def _f(v):
        try:
            return float(v) if v not in (None, "", "nan", "None") else None
        except (TypeError, ValueError):
            return None
    return {
        "signal":      signal.get("signal"),
        "direction":   signal.get("direction"),
        "entry":       _f(signal.get("entry")),
        "tp":          _f(signal.get("tp")),
        "sl":          _f(signal.get("sl")),
        "rr":          _f(signal.get("rr")),
        "prob":        _f(signal.get("prob")),
        "est_minutes": _f(signal.get("est_minutes")),
        "opened_at":   signal.get("opened_at", ""),
    }


def _build_tick() -> dict:
    global _prev_price

    kline = read_latest_kline()
    feat  = read_latest_features()
    price = kline["close"] if kline else None

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

    cvd_1m = round(_f(feat, "cvd_delta_1m") or 0.0, 2)

    prob_long,  curve_long,  ttc_long  = (_predict_cascade(feat, "long")  if feat else (None, {}, None))
    prob_short, curve_short, ttc_short = (_predict_cascade(feat, "short") if feat else (None, {}, None))

    # Signal: ưu tiên paper trade đang mở
    active_paper = read_active_signal()
    if active_paper:
        raw_sig = {**active_paper}
        if "signal" not in raw_sig:
            raw_sig["signal"] = "CASCADE_LONG"
        cascade_signal = _sig_dict(raw_sig)
    else:
        raw_sig = _predict_signal(feat, price) if feat else None
        cascade_signal = _sig_dict(raw_sig)

    return {
        "ts":                  kline["ts"] if kline else None,
        "price":               price,
        "price_change_pct":    price_change_pct,
        "imbalance":           _f(feat, "imbalance_now"),
        "cvd_1m":              cvd_1m,
        "funding_rate":        _f(feat, "funding_rate"),
        "delta_oi_1m":         _f(feat, "delta_oi_1m"),
        "cascade_prob_long":   prob_long,
        "cascade_prob_short":  prob_short,
        "cascade_curve_long":  curve_long  or {},
        "cascade_curve_short": curve_short or {},
        "time_to_cascade_long":  ttc_long,
        "time_to_cascade_short": ttc_short,
        "cascade_signal":      cascade_signal,
    }


def _broadcast_loop():
    time.sleep(3)
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    channel_layer = get_channel_layer()
    print("[BC] Broadcaster started — pushing tick every 1s")
    reload_counter = 0

    while True:
        try:
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
