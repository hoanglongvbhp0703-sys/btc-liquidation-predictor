"""
predict.py — Load model và predict single row (dùng bởi Tầng 5)

API:
    from ml.predict import load_model, predict_proba, predict_signal

    model_ctx = load_model()
    prob      = predict_proba(model_ctx, feature_row)
    signal    = predict_signal(model_ctx, feature_row, current_price, liq_zone_upper, liq_zone_lower)
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR     = Path(__file__).parent
SAVED_DIR    = BASE_DIR / "artifacts"
MODEL_FILE   = SAVED_DIR / "lgb_model.pkl"
IMPUTER_FILE = SAVED_DIR / "imputer.pkl"
META_FILE    = SAVED_DIR / "meta.json"

MIN_RR = 1.5   # R:R tối thiểu để phát signal


def load_model() -> dict:
    """
    Load model, imputer, metadata từ saved/.
    Returns dict context để truyền vào predict_proba / predict_signal.
    """
    if not MODEL_FILE.exists():
        raise FileNotFoundError(
            f"Model chưa được train. Chạy: python model/train.py\n"
            f"(Cần ít nhất 200 labeled rows trong features_5m.csv)"
        )

    with open(MODEL_FILE, "rb") as f:
        model = pickle.load(f)

    with open(IMPUTER_FILE, "rb") as f:
        imputer = pickle.load(f)

    with open(META_FILE) as f:
        meta = json.load(f)

    return {
        "model":     model,
        "imputer":   imputer,
        "features":  meta["feature_cols"],
        "threshold": meta["signal_threshold"],
        "meta":      meta,
    }


def predict_proba(ctx: dict, feature_row: dict) -> float:
    """
    Tính P(label=1) cho 1 feature row.

    Args:
        ctx:         output của load_model()
        feature_row: dict từ build_features.build_feature_row()

    Returns:
        float trong [0, 1]
    """
    features = ctx["features"]
    model    = ctx["model"]
    imputer  = ctx["imputer"]

    # Build vector theo đúng thứ tự features
    row_values = []
    for col in features:
        val = feature_row.get(col)

        # Boolean columns → int
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

    X = pd.DataFrame([row_values], columns=features, dtype=float)
    X = imputer.transform(X)
    return float(model.predict_proba(X)[0][1])


def predict_signal(
    ctx:             dict,
    feature_row:     dict,
    current_price:   float,
    liq_zone_upper:  float | None,
    liq_zone_lower:  float | None,
) -> dict | None:
    """
    Tính signal đầy đủ (LONG) nếu đủ điều kiện.

    Điều kiện:
      1. prob >= threshold (default 0.70)
      2. liq_zone_upper và liq_zone_lower không None
      3. R:R = (TP - entry) / (entry - SL) >= MIN_RR (1.5)

    Returns:
        dict signal nếu thoả điều kiện, None nếu không.
    """
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


def model_info(ctx: dict) -> None:
    """In thông tin model đang dùng."""
    meta = ctx["meta"]
    print("\n── Model Info ──────────────────────────────")
    print(f"  Model type      : {meta.get('model_type', 'LightGBM')}")
    print(f"  Trained at      : {meta.get('trained_at', 'N/A')}")
    print(f"  Train rows      : {meta.get('n_train')}")
    print(f"  Test AUC        : {meta.get('auc_test')}")
    print(f"  Precision@{meta.get('signal_threshold')} : {meta.get('precision_at_threshold')}")
    print(f"  Recall@{meta.get('signal_threshold')}    : {meta.get('recall_at_threshold')}")
    print(f"  Signal threshold: {meta.get('signal_threshold')}")
    print(f"  Features used   : {len(meta.get('feature_cols', []))}")
    print()
    print("  Top 5 features:")
    fi = meta.get("feature_importance", {})
    top5 = sorted(fi.items(), key=lambda x: x[1], reverse=True)[:5]
    for feat, imp in top5:
        print(f"    {feat:<30} {imp}")
    print("────────────────────────────────────────────\n")


if __name__ == "__main__":
    ctx = load_model()
    model_info(ctx)
