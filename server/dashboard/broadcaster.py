"""
broadcaster.py — Background thread: đọc data mỗi 1s → push WebSocket

Tick payload:
  price, price_change_pct, ts
  imbalance, cvd_1m, funding_rate, delta_oi_1m
  cascade_prob_long, cascade_prob_short    — P(cascade trong 3m)
  cascade_curve_long, cascade_curve_short  — {1→p, 2→p, 3→p}
  time_to_cascade_long, time_to_cascade_short — ước tính phút
  cascade_signal — signal dict | None
"""

import sys
import time
import threading
import warnings
from pathlib import Path

# sklearn RandomForest phát warning này mỗi lần predict_proba — không có ích lợi
warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*")
warnings.filterwarnings("ignore", message=".*does not have valid feature names.*")

ROOT_DIR  = Path(__file__).parent.parent.parent

if str(ROOT_DIR / "ml") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "ml"))

sys.path.insert(0, str(ROOT_DIR))
from config import ML_DIR

MODEL_FILE = ML_DIR / "ens_cascade_long_3m.pkl"

from .data_reader import read_latest_kline, read_latest_features, read_active_signal

_model_ctx   = None
_model_mtime = None
_prev_price  = None
_started     = False
_lock        = threading.Lock()

# Cache predictions per feature-row timestamp — re-run model only when features update (~1 min)
_pred_cache: dict = {}
_pred_cache_ts: str | None = None
_sig_cache: dict | None = None
_sig_cache_ts: str | None = None


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
    """Returns (prob, curve_dict, time_to_cascade)."""
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


def _get_predictions(feat: dict) -> tuple:
    """Run model predictions, caching result per feature timestamp.

    Features update every ~60s — no need to run the ensemble on every 1s tick.
    Returns (prob_long, curve_long, ttc_long, prob_short, curve_short, ttc_short).
    """
    global _pred_cache, _pred_cache_ts

    feat_ts = feat.get("timestamp") if feat else None

    if feat_ts is not None and feat_ts == _pred_cache_ts:
        return (
            _pred_cache.get("prob_long"),
            _pred_cache.get("curve_long", {}),
            _pred_cache.get("ttc_long"),
            _pred_cache.get("prob_short"),
            _pred_cache.get("curve_short", {}),
            _pred_cache.get("ttc_short"),
        )

    prob_long,  curve_long,  ttc_long  = _predict_cascade(feat, "long")
    prob_short, curve_short, ttc_short = _predict_cascade(feat, "short")

    _pred_cache_ts = feat_ts
    _pred_cache = {
        "prob_long":   prob_long,  "curve_long":  curve_long,  "ttc_long":  ttc_long,
        "prob_short":  prob_short, "curve_short": curve_short, "ttc_short": ttc_short,
    }

    return prob_long, curve_long, ttc_long, prob_short, curve_short, ttc_short


def _predict_signal(feature_row: dict, price: float) -> dict | None:
    global _sig_cache, _sig_cache_ts
    if _model_ctx is None or price is None:
        return None

    feat_ts = feature_row.get("timestamp") if feature_row else None
    if feat_ts is not None and feat_ts == _sig_cache_ts:
        return _sig_cache

    try:
        import predict as _predict
        result = _predict.predict_cascade_signal(_model_ctx, feature_row, price)
    except Exception:
        result = None

    _sig_cache_ts = feat_ts
    _sig_cache    = result
    return result


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

    prob_long, curve_long, ttc_long, prob_short, curve_short, ttc_short = (
        _get_predictions(feat) if feat else (None, {}, None, None, {}, None)
    )

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
