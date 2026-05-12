"""
train.py — Tầng 4: Train cascade liquidation models

Model A (binary classification) — 12 models:
  lgb_cascade_long_{h}m.pkl + lgb_cascade_short_{h}m.pkl (h ∈ {5,10,15,20,25,30})
  Predict: P(cascade xảy ra trong hm tới)

Model B (regression) — 2 models:
  lgb_ttc_long.pkl, lgb_ttc_short.pkl
  Predict: time_to_cascade (phút, 5-30), hay 35 nếu không có cascade trong 30m

Output artifacts: ml/artifacts/
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor, early_stopping, log_evaluation
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, precision_score, recall_score, mean_absolute_error

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, ML_DIR, HORIZONS, MIN_ROWS_TRAIN, SIGNAL_THRESHOLD

SAVED_DIR          = ML_DIR
TRAIN_RATIO        = 0.80
VAL_RATIO_OF_TRAIN = 0.15

FEATURE_COLS = [
    "price_change_1m", "price_change_30s", "volatility_1m",
    "volume_1m", "taker_buy_ratio",
    "liq_long_usd_1m", "liq_short_usd_1m", "liq_total_1m", "liq_ratio_1m",
    "liq_accel_30s",
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio",
    "cvd_delta_1m", "cvd_delta_30s",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_1m", "whale_sell_usd_1m", "whale_dominance",
    "delta_oi_1m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",
]


def load_labeled_data() -> pd.DataFrame:
    df = pd.read_csv(FEATURES_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURE_COLS].copy()
    for col in ("funding_long_heavy", "funding_short_heavy"):
        if col in X.columns:
            X[col] = X[col].astype(str).map(
                {"True": 1, "False": 0, "1": 1, "0": 0, "1.0": 1, "0.0": 0}
            ).astype(float)
    return X


def time_split(df: pd.DataFrame):
    n       = len(df)
    n_train = int(n * TRAIN_RATIO)
    n_val   = int(n_train * VAL_RATIO_OF_TRAIN)
    return df.iloc[:n_train - n_val], df.iloc[n_train - n_val:n_train], df.iloc[n_train:]


# ── Model A: binary classifier ────────────────────────────────────

def _train_classifier(df_all: pd.DataFrame, label_col: str, direction: str, horizon: int) -> dict | None:
    if label_col not in df_all.columns:
        print(f"[TRAIN-A] {direction}/{horizon}m: cột '{label_col}' chưa có — bỏ qua.")
        return None

    df = df_all.copy()
    df[label_col] = pd.to_numeric(df[label_col], errors="coerce")
    df = df[df[label_col].isin([0, 1])].copy()
    df[label_col] = df[label_col].astype(int)

    n_total    = len(df)
    n_positive = (df[label_col] == 1).sum()
    pct1 = f"{n_positive/n_total*100:.1f}%" if n_total > 0 else "N/A"

    print(f"\n[TRAIN-A] ── cascade_{direction} {horizon}m ──────────────────────")
    print(f"[TRAIN-A]   Rows: {n_total}  pos={n_positive} ({pct1})")

    if n_total < MIN_ROWS_TRAIN:
        print(f"[TRAIN-A]   Cần ít nhất {MIN_ROWS_TRAIN} rows. Bỏ qua.")
        return None
    if n_positive == 0:
        print(f"[TRAIN-A]   Không có label=1. Bỏ qua.")
        return None

    df_inner, df_val, df_test = time_split(df)

    X_inner = prepare_features(df_inner)
    X_val   = prepare_features(df_val)
    X_test  = prepare_features(df_test)
    y_inner = df_inner[label_col].values
    y_val   = df_val[label_col].values
    y_test  = df_test[label_col].values

    imputer     = SimpleImputer(strategy="median")
    X_inner_imp = imputer.fit_transform(X_inner)
    X_val_imp   = imputer.transform(X_val)
    X_test_imp  = imputer.transform(X_test)

    spw = (y_inner == 0).sum() / max((y_inner == 1).sum(), 1)

    model = LGBMClassifier(
        n_estimators=500, num_leaves=31, learning_rate=0.05,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
        min_child_samples=20, scale_pos_weight=spw,
        random_state=42, verbose=-1, n_jobs=-1,
    )
    model.fit(
        X_inner_imp, y_inner,
        eval_set=[(X_val_imp, y_val)],
        callbacks=[early_stopping(30, verbose=False), log_evaluation(-1)],
    )

    prob_test = model.predict_proba(X_test_imp)[:, 1]
    auc_test  = roc_auc_score(y_test, prob_test) if len(np.unique(y_test)) > 1 else float("nan")

    pred_test = (prob_test >= SIGNAL_THRESHOLD).astype(int)
    n_signals = int(pred_test.sum())
    prec = precision_score(y_test, pred_test, zero_division=0) if n_signals > 0 else 0.0
    rec  = recall_score(y_test, pred_test, zero_division=0) if n_signals > 0 else 0.0

    print(f"[TRAIN-A]   AUC test={auc_test:.4f} | @{SIGNAL_THRESHOLD}: signals={n_signals} prec={prec:.3f} rec={rec:.3f}")

    suffix       = f"cascade_{direction}_{horizon}m"
    model_file   = SAVED_DIR / f"lgb_{suffix}.pkl"
    imputer_file = SAVED_DIR / f"imputer_{suffix}.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(model, f)
    with open(imputer_file, "wb") as f:
        pickle.dump(imputer, f)

    print(f"[TRAIN-A]   Saved → {model_file.name}")

    return {
        "n_train": int(len(X_inner)), "n_test": int(len(X_test)),
        "auc_test": round(float(auc_test), 4) if not np.isnan(auc_test) else None,
        "precision": round(float(prec), 4), "recall": round(float(rec), 4),
        "n_signals_test": n_signals, "scale_pos_weight": round(float(spw), 4),
    }


# ── Model B: regression ────────────────────────────────────────────

def _train_regressor(df_all: pd.DataFrame, direction: str) -> dict | None:
    ttc_col = f"time_to_cascade_{direction}"
    if ttc_col not in df_all.columns:
        print(f"[TRAIN-B] {ttc_col} chưa có — bỏ qua.")
        return None

    df = df_all.copy()
    df[ttc_col] = pd.to_numeric(df[ttc_col], errors="coerce")
    # NaN (no cascade) → NO_CASCADE_VALUE
    df[ttc_col] = df[ttc_col].fillna(NO_CASCADE_VALUE)
    df = df.dropna(subset=[ttc_col])

    n_total    = len(df)
    n_cascade  = (df[ttc_col] < NO_CASCADE_VALUE).sum()
    print(f"\n[TRAIN-B] ── time_to_cascade_{direction} ──────────────────────")
    print(f"[TRAIN-B]   Rows: {n_total} | with cascade: {n_cascade}")

    if n_total < MIN_ROWS_TRAIN:
        print(f"[TRAIN-B]   Cần ít nhất {MIN_ROWS_TRAIN} rows. Bỏ qua.")
        return None
    if n_cascade < 20:
        print(f"[TRAIN-B]   Cần ít nhất 20 cascade rows. Bỏ qua.")
        return None

    df_inner, df_val, df_test = time_split(df)

    X_inner = prepare_features(df_inner)
    X_val   = prepare_features(df_val)
    X_test  = prepare_features(df_test)
    y_inner = df_inner[ttc_col].values
    y_val   = df_val[ttc_col].values
    y_test  = df_test[ttc_col].values

    imputer     = SimpleImputer(strategy="median")
    X_inner_imp = imputer.fit_transform(X_inner)
    X_val_imp   = imputer.transform(X_val)
    X_test_imp  = imputer.transform(X_test)

    model = LGBMRegressor(
        n_estimators=500, num_leaves=31, learning_rate=0.05,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
        min_child_samples=20, random_state=42, verbose=-1, n_jobs=-1,
    )
    model.fit(
        X_inner_imp, y_inner,
        eval_set=[(X_val_imp, y_val)],
        callbacks=[early_stopping(30, verbose=False), log_evaluation(-1)],
    )

    pred_test = model.predict(X_test_imp)
    mae = mean_absolute_error(y_test, pred_test)
    print(f"[TRAIN-B]   MAE={mae:.2f}m")

    model_file   = SAVED_DIR / f"lgb_ttc_{direction}.pkl"
    imputer_file = SAVED_DIR / f"imputer_ttc_{direction}.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(model, f)
    with open(imputer_file, "wb") as f:
        pickle.dump(imputer, f)

    print(f"[TRAIN-B]   Saved → {model_file.name}")
    return {"n_train": int(len(X_inner)), "n_test": int(len(X_test)), "mae": round(float(mae), 2)}


# ── Main ──────────────────────────────────────────────────────────

def train():
    SAVED_DIR.mkdir(exist_ok=True)

    print("[TRAIN] Đọc features_1m.csv...")
    df = load_labeled_data()
    print(f"[TRAIN] Total rows: {len(df)}")

    all_metrics = {"long": {}, "short": {}}

    for direction in ("long", "short"):
        for h in HORIZONS:
            lc = f"cascade_{direction}_{h}m"
            try:
                m = _train_classifier(df, lc, direction, h)
                if m:
                    all_metrics[direction][f"{h}m"] = m
            except Exception as e:
                print(f"[TRAIN-A] {direction}/{h}m lỗi: {e}")

    trained_a = sum(1 for d in ("long", "short") for v in all_metrics[d].values() if v)

    if trained_a == 0:
        print("[TRAIN] Không có model nào được train.")
        return

    # Tính avg AUC cho meta
    aucs = [
        v["auc_test"]
        for d in ("long", "short")
        for v in all_metrics[d].values()
        if v and v.get("auc_test") is not None
    ]
    avg_auc = round(sum(aucs) / len(aucs), 4) if aucs else None

    meta = {
        "model_type":       "LightGBM cascade",
        "feature_cols":     FEATURE_COLS,
        "signal_threshold": SIGNAL_THRESHOLD,
        "trained_at":       pd.Timestamp.now(tz="UTC").isoformat(),
        "avg_auc_test":     avg_auc,
        "horizons":         all_metrics,
        # backward compat — auc_test dùng bởi auto_train.py
        "auc_test":         avg_auc,
    }

    with open(SAVED_DIR / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[TRAIN] Models: {trained_a}/6 | avg AUC={avg_auc}")
    print(f"[TRAIN] meta.json saved → {SAVED_DIR}/meta.json")


if __name__ == "__main__":
    train()
