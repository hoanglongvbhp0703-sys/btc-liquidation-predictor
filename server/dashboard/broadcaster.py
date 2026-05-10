"""
broadcaster.py — Background thread: đọc data mỗi 1s → push WebSocket

Tick payload:
  price, price_change_pct, liq_upper, liq_lower
  prob_long, prob_short       — xác suất LONG / SHORT
  signal_long, signal_short   — signal object nếu đủ điều kiện
  prob (alias prob_long cho backward compat)
  signal (alias signal_long cho backward compat)
"""

import sys
import time
import json
import threading
from pathlib import Path

ROOT_DIR   = Path(__file__).parent.parent.parent
MODEL_DIR  = ROOT_DIR / "ml"
MODEL_LONG = MODEL_DIR / "artifacts" / "lgb_model_long.pkl"
MODEL_OLD  = MODEL_DIR / "artifacts" / "lgb_model.pkl"

if str(MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(MODEL_DIR))

from .data_reader import (
    read_latest_kline, read_latest_features,
    read_active_signal,
)

_model_ctx   = None
_model_mtime = None
_prev_price  = None
_started     = False
_lock        = threading.Lock()


def _model_file_exists() -> bool:
    return MODEL_LONG.exists() or MODEL_OLD.exists()


def _current_model_mtime() -> float | None:
    f = MODEL_LONG if MODEL_LONG.exists() else (MODEL_OLD if MODEL_OLD.exists() else None)
    return f.stat().st_mtime if f else None


def _try_load_model():
    global _model_ctx, _model_mtime
    if not _model_file_exists():
        return
    try:
        mtime = _current_model_mtime()
        if mtime == _model_mtime:
            return
        import predict as _predict
        _model_ctx   = _predict.load_model()
        _model_mtime = mtime
        long_auc  = (_model_ctx["meta"].get("long") or {}).get("auc_test", "N/A")
        short_auc = (_model_ctx["meta"].get("short") or {}).get("auc_test", "N/A")
        has_short = _model_ctx.get("short") is not None
        print(f"[BC] Model loaded | LONG auc={long_auc} | SHORT {'auc=' + str(short_auc) if has_short else 'N/A'}")
    except Exception as e:
        print(f"[BC] Model load error: {e}")


def _compute_prob_long(feature_row: dict) -> float | None:
    if _model_ctx is None:
        return None
    try:
        import predict as _predict
        return round(_predict.predict_proba(_model_ctx, feature_row), 4)
    except Exception:
        return None


def _compute_prob_short(feature_row: dict) -> float | None:
    if _model_ctx is None or _model_ctx.get("short") is None:
        return None
    try:
        import predict as _predict
        prob = _predict.predict_proba_short(_model_ctx, feature_row)
        return round(prob, 4) if prob is not None else None
    except Exception:
        return None


def _compute_curve_long(feature_row: dict) -> dict | None:
    if _model_ctx is None:
        return None
    try:
        import predict as _predict
        return _predict.predict_curve_long(_model_ctx, feature_row)
    except Exception:
        return None


def _compute_curve_short(feature_row: dict) -> dict | None:
    if _model_ctx is None:
        return None
    try:
        import predict as _predict
        return _predict.predict_curve_short(_model_ctx, feature_row)
    except Exception:
        return None


def _compute_signal_long(feature_row: dict, price: float, upper, lower) -> dict | None:
    if _model_ctx is None or price is None:
        return None
    try:
        import predict as _predict
        return _predict.predict_signal(_model_ctx, feature_row, price, upper, lower)
    except Exception:
        return None


def _compute_signal_short(feature_row: dict, price: float, upper, lower) -> dict | None:
    if _model_ctx is None or _model_ctx.get("short") is None or price is None:
        return None
    try:
        import predict as _predict
        return _predict.predict_signal_short(_model_ctx, feature_row, price, upper, lower)
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
        "signal":     signal.get("signal"),
        "entry":      _f(signal.get("entry")),
        "tp":         _f(signal.get("tp")),
        "sl":         _f(signal.get("sl")),
        "rr":         _f(signal.get("rr")),
        "prob":       _f(signal.get("prob")),
        "opened_at":  signal.get("opened_at", ""),
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

    liq_upper = _f(feat, "liq_zone_upper")
    liq_lower = _f(feat, "liq_zone_lower")

    cvd_5m = round(_f(feat, "cvd_delta_5m") or 0.0, 2)

    prob_long        = _compute_prob_long(feat)   if feat else None
    prob_short       = _compute_prob_short(feat)  if feat else None
    prob_curve_long  = _compute_curve_long(feat)  if feat else None
    prob_curve_short = _compute_curve_short(feat) if feat else None

    # Signal LONG: ưu tiên paper trade đang mở (từ signal/run.py)
    # Signal SHORT: tính real-time từ broadcaster
    active_paper = read_active_signal()
    if active_paper:
        sig_long = _sig_dict({**active_paper, "signal": "LONG"})
    else:
        raw_long = _compute_signal_long(feat, price, liq_upper, liq_lower) if feat else None
        sig_long = _sig_dict(raw_long)

    raw_short = _compute_signal_short(feat, price, liq_upper, liq_lower) if feat else None
    sig_short = _sig_dict(raw_short)

    return {
        "ts":               kline["ts"] if kline else None,
        "price":            price,
        "price_change_pct": price_change_pct,
        "liq_upper":        liq_upper,
        "liq_lower":        liq_lower,
        "dist_upper_pct":   _f(feat, "dist_to_upper"),
        "imbalance":        _f(feat, "imbalance_now"),
        "cvd_5m":           cvd_5m,
        "funding_rate":     _f(feat, "funding_rate"),
        "delta_oi_5m":      _f(feat, "delta_oi_5m"),
        "prob_long":        prob_long,
        "prob_short":       prob_short,
        "prob_curve_long":  prob_curve_long,
        "prob_curve_short": prob_curve_short,
        "signal_long":      sig_long,
        "signal_short":     sig_short,
        # backward compat
        "prob":   prob_long,
        "signal": sig_long,
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
