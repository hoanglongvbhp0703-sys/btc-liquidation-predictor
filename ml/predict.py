"""
predict.py — Load model và predict LONG + SHORT (dùng bởi Tầng 5 và broadcaster)

API:
    from ml.predict import load_model, predict_proba, predict_signal
    from ml.predict import predict_proba_short, predict_signal_short
    from ml.predict import predict_curve_long, predict_curve_short

    ctx    = load_model()
    prob_l = predict_proba(ctx, feature_row)           # LONG prob 30m
    prob_s = predict_proba_short(ctx, feature_row)     # SHORT prob 30m
    curve_l = predict_curve_long(ctx, feature_row)     # {5: p, 10: p, ..., 30: p}
    curve_s = predict_curve_short(ctx, feature_row)    # {5: p, 10: p, ..., 30: p}
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

HORIZONS = [5, 10, 15, 20, 25, 30]
MIN_RR   = 1.5


def _load_artifact(model_file: Path, imputer_file: Path) -> dict | None:
    if not model_file.exists() or not imputer_file.exists():
        return None
    with open(model_file, "rb") as f:
        model = pickle.load(f)
    with open(imputer_file, "rb") as f:
        imputer = pickle.load(f)
    return {"model": model, "imputer": imputer}


def load_model() -> dict:
    """
    Load tất cả LONG và SHORT models cho 6 horizons.
    ctx["long"] / ctx["short"] = 30m model (backward compat).
    ctx["long_curves"] / ctx["short_curves"] = {h: artifact} cho từng horizon.
    """
    meta = {}
    if META_FILE.exists():
        with open(META_FILE) as f:
            meta = json.load(f)

    threshold = meta.get("signal_threshold", 0.70)
    features  = meta.get("feature_cols", [])

    long_curves  = {}
    short_curves = {}

    for h in HORIZONS:
        # LONG
        lf = SAVED_DIR / f"lgb_model_long_{h}m.pkl"
        li = SAVED_DIR / f"imputer_long_{h}m.pkl"
        # fallback tên cũ cho 30m
        if h == 30 and not lf.exists():
            lf = SAVED_DIR / "lgb_model_long.pkl"
            li = SAVED_DIR / "imputer_long.pkl"
        long_curves[h] = _load_artifact(lf, li)

        # SHORT
        sf = SAVED_DIR / f"lgb_model_short_{h}m.pkl"
        si = SAVED_DIR / f"imputer_short_{h}m.pkl"
        if h == 30 and not sf.exists():
            sf = SAVED_DIR / "lgb_model_short.pkl"
            si = SAVED_DIR / "imputer_short.pkl"
        short_curves[h] = _load_artifact(sf, si)

    long_30m  = long_curves.get(30)
    short_30m = short_curves.get(30)

    # Thêm fallback lgb_model.pkl (legacy)
    if long_30m is None:
        long_30m = _load_artifact(SAVED_DIR / "lgb_model.pkl", SAVED_DIR / "imputer.pkl")
        long_curves[30] = long_30m

    if long_30m is None:
        raise FileNotFoundError(
            "Model chưa được train. Chạy: python ml/train.py\n"
            "(Cần ít nhất 200 labeled rows trong features_5m.csv)"
        )

    n_long  = sum(1 for v in long_curves.values()  if v is not None)
    n_short = sum(1 for v in short_curves.values() if v is not None)
    long_auc  = (meta.get("long")  or {}).get("auc_test", "N/A")
    short_auc = (meta.get("short") or {}).get("auc_test", "N/A")
    print(f"[PREDICT] Loaded LONG {n_long}/6 horizons (30m auc={long_auc}) | "
          f"SHORT {n_short}/6 horizons (30m auc={short_auc})")

    return {
        # backward compat
        "long":         {**long_30m,  "threshold": threshold},
        "short":        {**short_30m, "threshold": threshold} if short_30m else None,
        # curve models
        "long_curves":  long_curves,
        "short_curves": short_curves,
        "features":     features,
        "threshold":    threshold,
        "meta":         meta,
    }


def _build_input(ctx: dict, feature_row: dict) -> pd.DataFrame:
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

    return pd.DataFrame([row_values], columns=features, dtype=float)


def predict_proba(ctx: dict, feature_row: dict) -> float:
    """P(LONG label=1) — giá chạm Liq Upper trong 30m."""
    sub = ctx["long"]
    X   = _build_input(ctx, feature_row)
    return float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1])


def predict_proba_short(ctx: dict, feature_row: dict) -> float | None:
    """P(SHORT label=1) — giá chạm Liq Lower trong 30m. None nếu chưa train."""
    sub = ctx.get("short")
    if sub is None:
        return None
    X = _build_input(ctx, feature_row)
    return float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1])


def predict_curve_long(ctx: dict, feature_row: dict) -> dict:
    """
    Xác suất LONG chạm Liq Upper tại từng horizon.
    Returns {5: prob, 10: prob, ..., 30: prob} — None nếu model chưa có.
    """
    X      = _build_input(ctx, feature_row)
    curves = ctx.get("long_curves", {})
    result = {}
    for h in HORIZONS:
        sub = curves.get(h)
        if sub is None:
            result[h] = None
            continue
        result[h] = round(float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1]), 4)
    return result


def predict_curve_short(ctx: dict, feature_row: dict) -> dict:
    """
    Xác suất SHORT chạm Liq Lower tại từng horizon.
    Returns {5: prob, 10: prob, ..., 30: prob} — None nếu model chưa có.
    """
    X      = _build_input(ctx, feature_row)
    curves = ctx.get("short_curves", {})
    result = {}
    for h in HORIZONS:
        sub = curves.get(h)
        if sub is None:
            result[h] = None
            continue
        result[h] = round(float(sub["model"].predict_proba(sub["imputer"].transform(X))[0][1]), 4)
    return result


def predict_signal(
    ctx: dict,
    feature_row: dict,
    current_price: float,
    liq_zone_upper: float | None,
    liq_zone_lower: float | None,
) -> dict | None:
    if liq_zone_upper is None or liq_zone_lower is None:
        return None
    if current_price >= liq_zone_upper:
        return None

    prob = predict_proba(ctx, feature_row)
    if prob < ctx["threshold"]:
        return None

    tp = liq_zone_upper
    sl = liq_zone_lower
    rr = (tp - current_price) / (current_price - sl) if current_price > sl else 0.0
    if rr < MIN_RR:
        return None

    return {
        "signal":    "LONG",
        "prob":      round(prob, 4),
        "entry":     round(current_price, 2),
        "tp":        round(tp, 2),
        "sl":        round(sl, 2),
        "rr":        round(rr, 2),
        "threshold": ctx["threshold"],
    }


def predict_signal_short(
    ctx: dict,
    feature_row: dict,
    current_price: float,
    liq_zone_upper: float | None,
    liq_zone_lower: float | None,
) -> dict | None:
    if liq_zone_upper is None or liq_zone_lower is None:
        return None
    if current_price <= liq_zone_lower:
        return None

    prob = predict_proba_short(ctx, feature_row)
    if prob is None or prob < ctx["threshold"]:
        return None

    tp = liq_zone_lower
    sl = liq_zone_upper
    rr = (current_price - tp) / (sl - current_price) if sl > current_price else 0.0
    if rr < MIN_RR:
        return None

    return {
        "signal":    "SHORT",
        "prob":      round(prob, 4),
        "entry":     round(current_price, 2),
        "tp":        round(tp, 2),
        "sl":        round(sl, 2),
        "rr":        round(rr, 2),
        "threshold": ctx["threshold"],
    }


def model_info(ctx: dict) -> None:
    meta = ctx["meta"]
    print("\n── Model Info ──────────────────────────────")
    print(f"  Trained at : {meta.get('trained_at', 'N/A')}")
    print(f"  Threshold  : {meta.get('signal_threshold')}")
    horizons_meta = meta.get("horizons", {})
    for direction in ("long", "short"):
        sub_ctx = ctx.get(direction)
        status  = "✅" if sub_ctx else "❌ chưa train"
        print(f"\n  {direction.upper()} {status}")
        dir_meta = horizons_meta.get(direction, {})
        for hm, hm_meta in dir_meta.items():
            auc = hm_meta.get("auc_test", "N/A") if hm_meta else "N/A"
            print(f"    {hm:>4}  AUC={auc}")
    print("────────────────────────────────────────────\n")


if __name__ == "__main__":
    ctx = load_model()
    model_info(ctx)
