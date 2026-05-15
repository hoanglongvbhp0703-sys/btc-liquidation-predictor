"""
predict.py — Cascade liquidation prediction

Model = RandomForest + Platt scaling (artifact: ens_cascade_{dir}_{h}m.pkl)
Falls back to legacy LightGBM pkl if RF artifact missing.

API:
    ctx = load_model()
    prob = predict_cascade_prob(ctx, feature_row, "long")
    curve = predict_cascade_curve(ctx, feature_row, "long")
    signal = predict_cascade_signal(ctx, feature_row, price)
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
CASCADE_TP_PCT   = 0.0012   # p75 of actual cascade amplitude (~0.12%)
CASCADE_SL_PCT   = 0.0012   # 1:1 R:R → EV > 0 at precision ≥ 50%


def _load_artifact(suffix: str) -> dict | None:
    """Load ensemble artifact. Falls back to legacy lgb pkl if ensemble not found."""
    ens_file = SAVED_DIR / f"ens_{suffix}.pkl"
    if ens_file.exists():
        with open(ens_file, "rb") as f:
            return {"ensemble": pickle.load(f)}

    # fallback: legacy LightGBM single model
    lgb_file     = SAVED_DIR / f"lgb_{suffix}.pkl"
    imputer_file = SAVED_DIR / f"imputer_{suffix}.pkl"
    if lgb_file.exists() and imputer_file.exists():
        with open(lgb_file, "rb") as f:
            model = pickle.load(f)
        with open(imputer_file, "rb") as f:
            imputer = pickle.load(f)
        return {"legacy": {"model": model, "imputer": imputer}}

    return None


def _predict_proba_from_artifact(artifact: dict, X_raw: np.ndarray) -> float:
    """Trả về prob từ RF artifact hoặc legacy LightGBM."""
    if "ensemble" in artifact:
        ens         = artifact["ensemble"]
        imputer     = ens["imputer"]
        models      = ens["models"]
        model_names = ens.get("model_names", [])
        X_imp       = imputer.transform(X_raw)

        scaler = ens.get("scaler")
        X_sc   = scaler.transform(X_imp) if scaler is not None else None

        probs = []
        for i, m in enumerate(models):
            name = model_names[i] if i < len(model_names) else ""
            X_in = X_sc if (name == "LogisticReg" and X_sc is not None) else X_imp
            probs.append(m.predict_proba(X_in)[0][1])
        return float(np.mean(probs))

    # legacy LightGBM
    leg   = artifact["legacy"]
    X_imp = leg["imputer"].transform(X_raw)
    return float(leg["model"].predict_proba(X_imp)[0][1])


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
        long_curves[h]  = _load_artifact(f"cascade_long_{h}m")
        short_curves[h] = _load_artifact(f"cascade_short_{h}m")

    if long_curves.get(3) is None:
        raise FileNotFoundError(
            "Model chưa được train. Chạy: python ml/train.py\n"
            "(Cần ít nhất 200 labeled rows trong features_1m.csv)"
        )

    n_long  = sum(1 for v in long_curves.values()  if v)
    n_short = sum(1 for v in short_curves.values() if v)
    avg_auc = meta.get("avg_auc_test", "N/A")
    mtype   = meta.get("model_type", "unknown")
    print(f"[PREDICT] Loaded LONG {n_long}/3 | SHORT {n_short}/3 | avg_auc={avg_auc}")
    print(f"[PREDICT] Model type: {mtype}")

    return {
        "long_curves":  long_curves,
        "short_curves": short_curves,
        "features":     features,
        "threshold":    threshold,
        "meta":         meta,
    }


def _build_input(ctx: dict, feature_row: dict) -> np.ndarray:
    features   = ctx["features"]
    row_values = []
    _bool_cols = {"funding_long_heavy", "funding_short_heavy", "basis_positive"}
    for col in features:
        val = feature_row.get(col)
        if col in _bool_cols:
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
    """Max prob across all horizons (1m/2m/3m)."""
    curves = ctx.get(f"{direction}_curves", {})
    X      = _build_input(ctx, feature_row)
    probs  = [
        _predict_proba_from_artifact(sub, X)
        for h, sub in curves.items()
        if sub is not None
    ]
    return round(max(probs), 4) if probs else None


def predict_cascade_curve(ctx: dict, feature_row: dict, direction: str) -> dict:
    """Xác suất cascade tại từng horizon {1→p, 2→p, 3→p}."""
    curves = ctx.get(f"{direction}_curves", {})
    X      = _build_input(ctx, feature_row)
    result = {}
    for h in HORIZONS:
        sub = curves.get(h)
        if sub is None:
            result[h] = None
            continue
        result[h] = round(_predict_proba_from_artifact(sub, X), 4)
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
        print(f"  {direction.upper():5}: {n}/3 horizon models")
    print("────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    ctx = load_model()
    model_info(ctx)
