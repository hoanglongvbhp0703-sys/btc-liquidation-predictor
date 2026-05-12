"""
predict.py — Cascade liquidation prediction

API:
    ctx = load_model()
    prob = predict_cascade_prob(ctx, feature_row, "long")   # P(cascade trong 30m)
    curve = predict_cascade_curve(ctx, feature_row, "long") # {5:p, 10:p, ..., 30:p}
    minutes = predict_time_to_cascade(ctx, feature_row, "long")  # ước tính phút
    signal = predict_cascade_signal(ctx, feature_row, price)     # dict | None
"""

import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="X does not have valid feature names")

BASE_DIR  = Path(__file__).parent
SAVED_DIR = BASE_DIR / "artifacts"
META_FILE = SAVED_DIR / "meta.json"

HORIZONS         = [1, 2, 3]
CASCADE_TP_PCT   = 0.008   # +0.8%
CASCADE_SL_PCT   = 0.005   # -0.5%


def _load_artifact(model_file: Path, imputer_file: Path) -> dict | None:
    if not model_file.exists() or not imputer_file.exists():
        return None
    with open(model_file, "rb") as f:
        model = pickle.load(f)
    with open(imputer_file, "rb") as f:
        imputer = pickle.load(f)
    return {"model": model, "imputer": imputer}


def load_model() -> dict:
    meta = {}
    if META_FILE.exists():
        with open(META_FILE) as f:
            meta = json.load(f)

    threshold = meta.get("signal_threshold", 0.70)
    features  = meta.get("feature_cols", [])

    long_curves  = {}
    short_curves = {}

    for h in HORIZONS:
        long_curves[h] = _load_artifact(
            SAVED_DIR / f"lgb_cascade_long_{h}m.pkl",
            SAVED_DIR / f"imputer_cascade_long_{h}m.pkl",
        )
        short_curves[h] = _load_artifact(
            SAVED_DIR / f"lgb_cascade_short_{h}m.pkl",
            SAVED_DIR / f"imputer_cascade_short_{h}m.pkl",
        )

    ttc_long  = None
    ttc_short = None

    # Cần ít nhất 3m model để hoạt động
    if long_curves.get(3) is None:
        raise FileNotFoundError(
            "Model chưa được train. Chạy: python ml/train.py\n"
            "(Cần ít nhất 200 labeled rows trong features_1m.csv)"
        )

    n_long  = sum(1 for v in long_curves.values()  if v)
    n_short = sum(1 for v in short_curves.values() if v)
    avg_auc = meta.get("avg_auc_test", "N/A")
    print(f"[PREDICT] Loaded LONG {n_long}/3 | SHORT {n_short}/3 | avg_auc={avg_auc}")

    return {
        "long_curves":  long_curves,
        "short_curves": short_curves,
        "ttc_long":     ttc_long,
        "ttc_short":    ttc_short,
        "features":     features,
        "threshold":    threshold,
        "meta":         meta,
    }


def _build_input(ctx: dict, feature_row: dict) -> np.ndarray:
    features   = ctx["features"]
    row_values = []
    for col in features:
        val = feature_row.get(col)
        if col in ("funding_long_heavy", "funding_short_heavy"):
            if isinstance(val, bool):
                val = int(val)
            elif isinstance(val, str):
                val = 1 if val.lower() == "true" else 0
            elif val is None:
                val = np.nan
            else:
                val = float(val)
        else:
            val = np.nan if val is None else float(val)
        row_values.append(val)
    return np.array([row_values], dtype=float)


def predict_cascade_prob(ctx: dict, feature_row: dict, direction: str) -> float | None:
    """P(cascade trong 3m)."""
    curves = ctx.get(f"{direction}_curves", {})
    sub    = curves.get(3)
    if sub is None:
        return None
    X = _build_input(ctx, feature_row)
    return round(float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1]), 4)


def predict_cascade_curve(ctx: dict, feature_row: dict, direction: str) -> dict:
    """Xác suất cascade tại từng horizon. {5→p, 10→p, ..., 30→p}"""
    curves = ctx.get(f"{direction}_curves", {})
    X      = _build_input(ctx, feature_row)
    result = {}
    for h in HORIZONS:
        sub = curves.get(h)
        if sub is None:
            result[h] = None
            continue
        result[h] = round(float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1]), 4)
    return result


def predict_time_to_cascade(ctx: dict, feature_row: dict, direction: str) -> float | None:
    """Ước tính phút đến cascade từ curve: horizon nhỏ nhất mà prob >= 0.50."""
    curve = predict_cascade_curve(ctx, feature_row, direction)
    for h in HORIZONS:
        p = curve.get(h)
        if p is not None and p >= 0.50:
            return float(h)
    return None


def predict_cascade_signal(
    ctx: dict,
    feature_row: dict,
    current_price: float,
    max_ttc: float = 2.0,
) -> dict | None:
    """
    Signal condition:
      - cascade_prob_long >= threshold AND time_to_cascade_long <= max_ttc
      - cascade_prob_short >= threshold AND time_to_cascade_short <= max_ttc
    Ưu tiên LONG. Trả về signal dict hoặc None.
    """
    if current_price is None or current_price <= 0:
        return None

    threshold = ctx.get("threshold", 0.70)

    for direction in ("long", "short"):
        prob = predict_cascade_prob(ctx, feature_row, direction)
        if prob is None or prob < threshold:
            continue

        ttc = predict_time_to_cascade(ctx, feature_row, direction)
        if ttc is None or ttc > max_ttc:
            continue

        if direction == "long":
            tp  = round(current_price * (1 + CASCADE_TP_PCT), 2)
            sl  = round(current_price * (1 - CASCADE_SL_PCT), 2)
            sig = "CASCADE_LONG"
        else:
            tp  = round(current_price * (1 - CASCADE_TP_PCT), 2)
            sl  = round(current_price * (1 + CASCADE_SL_PCT), 2)
            sig = "CASCADE_SHORT"

        rr = CASCADE_TP_PCT / CASCADE_SL_PCT

        return {
            "signal":      sig,
            "direction":   direction,
            "prob":        round(prob, 4),
            "entry":       round(current_price, 2),
            "tp":          tp,
            "sl":          sl,
            "rr":          round(rr, 2),
            "est_minutes": ttc,
            "threshold":   threshold,
        }

    return None


def model_info(ctx: dict) -> None:
    meta = ctx["meta"]
    print("\n── Cascade Model Info ──────────────────────────────")
    print(f"  Trained at  : {meta.get('trained_at', 'N/A')}")
    print(f"  Avg AUC     : {meta.get('avg_auc_test', 'N/A')}")
    print(f"  Threshold   : {meta.get('signal_threshold')}")
    for direction in ("long", "short"):
        n = sum(1 for v in ctx.get(f"{direction}_curves", {}).values() if v)
        ttc = "✓" if ctx.get(f"ttc_{direction}") else "✗"
        print(f"  {direction.upper():5}: {n}/6 horizon models | ttc={ttc}")
    print("────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    ctx = load_model()
    model_info(ctx)
