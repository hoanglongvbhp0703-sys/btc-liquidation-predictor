"""
train.py — Tầng 4: Train LightGBM models (6 horizons × LONG + SHORT = 12 models)

    python ml/train.py

Output artifacts (ml/artifacts/):
    lgb_model_long_5m.pkl  … lgb_model_long_30m.pkl
    lgb_model_short_5m.pkl … lgb_model_short_30m.pkl
    imputer_long_5m.pkl    … imputer_long_30m.pkl
    imputer_short_5m.pkl   … imputer_short_30m.pkl
    lgb_model_long.pkl     (alias → 30m, backward compat)
    lgb_model_short.pkl    (alias → 30m, backward compat)
    meta.json
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, ML_DIR, HORIZONS, MIN_ROWS_TRAIN, SIGNAL_THRESHOLD

BASE_DIR  = Path(__file__).parent
SAVED_DIR = ML_DIR

MIN_ROWS_TO_TRAIN  = MIN_ROWS_TRAIN
TRAIN_RATIO        = 0.80
VAL_RATIO_OF_TRAIN = 0.15

FEATURE_COLS = [
    "price_change_5m", "price_change_1m", "volatility_5m",
    "volume_5m", "taker_buy_ratio",
    "liq_long_usd_5m", "liq_short_usd_5m", "liq_total_5m", "liq_ratio_5m",
    "dist_to_upper", "dist_to_lower",
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio",
    "cvd_delta_5m", "cvd_delta_1m",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_5m", "whale_sell_usd_5m", "whale_dominance",
    "delta_oi_5m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",
]


def _label_col(direction: str, minutes: int) -> str:
    if direction == "long":
        return "label" if minutes == 30 else f"label_{minutes}m"
    return "label_short" if minutes == 30 else f"label_short_{minutes}m"


def load_labeled_data() -> pd.DataFrame:
    df = pd.read_csv(FEATURES_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


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


def _train_one(df_all: pd.DataFrame, label_col: str, direction: str, horizon: int) -> dict | None:
    label_exists = label_col in df_all.columns
    if not label_exists:
        print(f"[TRAIN] {direction}/{horizon}m: cột '{label_col}' chưa có — bỏ qua.")
        return None

    df = df_all.copy()
    df[label_col] = pd.to_numeric(df[label_col], errors="coerce")
    df = df[df[label_col].isin([0, 1])].copy()
    df[label_col] = df[label_col].astype(int)

    n_total    = len(df)
    n_positive = (df[label_col] == 1).sum()
    n_negative = (df[label_col] == 0).sum()
    pct1 = f"{n_positive/n_total*100:.1f}%" if n_total > 0 else "N/A"

    print(f"\n[TRAIN] ── {direction.upper()} {horizon}m ─────────────────────────────────")
    print(f"[TRAIN]   Labeled rows : {n_total}  (pos={n_positive} {pct1}, neg={n_negative})")

    if n_total < MIN_ROWS_TO_TRAIN:
        print(f"[TRAIN]   ❌ Cần ít nhất {MIN_ROWS_TO_TRAIN} rows. Bỏ qua.")
        return None
    if n_positive == 0:
        print(f"[TRAIN]   ❌ Không có row label=1. Bỏ qua.")
        return None
    if n_total < 500:
        print(f"[TRAIN]   ⚠️  Chỉ {n_total} rows — khuyến nghị 2000+.")

    df_inner, df_val, df_test = time_split(df)

    X_inner = prepare_features(df_inner)
    X_val   = prepare_features(df_val)
    X_test  = prepare_features(df_test)
    y_inner = df_inner[label_col].values
    y_val   = df_val[label_col].values
    y_test  = df_test[label_col].values

    print(f"[TRAIN]   Split: inner={len(X_inner)} val={len(X_val)} test={len(X_test)}")

    imputer     = SimpleImputer(strategy="median")
    X_inner_imp = imputer.fit_transform(X_inner)
    X_val_imp   = imputer.transform(X_val)
    X_test_imp  = imputer.transform(X_test)

    n_neg = (y_inner == 0).sum()
    n_pos = (y_inner == 1).sum()
    spw   = n_neg / n_pos if n_pos > 0 else 1.0

    model = LGBMClassifier(
        n_estimators=500,
        num_leaves=31,
        learning_rate=0.05,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        min_child_samples=20,
        scale_pos_weight=spw,
        random_state=42,
        verbose=-1,
        n_jobs=-1,
    )
    model.fit(
        X_inner_imp, y_inner,
        eval_set=[(X_val_imp, y_val)],
        callbacks=[early_stopping(30, verbose=False), log_evaluation(-1)],
    )

    prob_train = model.predict_proba(X_inner_imp)[:, 1]
    prob_test  = model.predict_proba(X_test_imp)[:, 1]

    auc_train = roc_auc_score(y_inner, prob_train) if len(np.unique(y_inner)) > 1 else float("nan")
    auc_test  = roc_auc_score(y_test,  prob_test)  if len(np.unique(y_test))  > 1 else float("nan")

    pred_test = (prob_test >= SIGNAL_THRESHOLD).astype(int)
    n_signals = int(pred_test.sum())
    prec = precision_score(y_test, pred_test, zero_division=0) if n_signals > 0 else 0.0
    rec  = recall_score(y_test,  pred_test, zero_division=0) if n_signals > 0 else 0.0
    f1   = f1_score(y_test,     pred_test, zero_division=0) if n_signals > 0 else 0.0

    print(f"[TRAIN]   AUC train={auc_train:.4f}  test={auc_test:.4f}", end="")
    if not (np.isnan(auc_train) or np.isnan(auc_test)) and auc_train - auc_test > 0.10:
        print(f"  ⚠️  overfit gap={auc_train-auc_test:.3f}", end="")
    print()
    print(f"[TRAIN]   @{SIGNAL_THRESHOLD}: signals={n_signals}  prec={prec:.3f}  rec={rec:.3f}  f1={f1:.3f}")

    importance = model.feature_importances_
    fi = sorted(zip(FEATURE_COLS, importance), key=lambda x: x[1], reverse=True)
    print(f"[TRAIN]   Top 5 features:")
    for feat, imp in fi[:5]:
        print(f"    {feat:<30} {imp:>5.0f}")

    # Lưu model chính (tên có horizon)
    suffix       = f"{direction}_{horizon}m"
    model_file   = SAVED_DIR / f"lgb_model_{suffix}.pkl"
    imputer_file = SAVED_DIR / f"imputer_{suffix}.pkl"
    with open(model_file, "wb") as f:
        pickle.dump(model, f)
    with open(imputer_file, "wb") as f:
        pickle.dump(imputer, f)

    # Backward compat: 30m → lgb_model_long.pkl / lgb_model_short.pkl
    if horizon == 30:
        compat_model   = SAVED_DIR / f"lgb_model_{direction}.pkl"
        compat_imputer = SAVED_DIR / f"imputer_{direction}.pkl"
        with open(compat_model, "wb") as f:
            pickle.dump(model, f)
        with open(compat_imputer, "wb") as f:
            pickle.dump(imputer, f)

    print(f"[TRAIN]   ✅ Saved → {model_file.name} ({model_file.stat().st_size // 1024} KB)")

    return {
        "n_train":                int(len(X_inner)),
        "n_test":                 int(len(X_test)),
        "auc_train":              round(float(auc_train), 4) if not np.isnan(auc_train) else None,
        "auc_test":               round(float(auc_test),  4) if not np.isnan(auc_test)  else None,
        "precision_at_threshold": round(float(prec), 4),
        "recall_at_threshold":    round(float(rec),  4),
        "f1_at_threshold":        round(float(f1),   4),
        "n_signals_test":         n_signals,
        "scale_pos_weight":       round(float(spw), 4),
        "best_iteration":         int(model.best_iteration_) if model.best_iteration_ else None,
        "feature_importance":     {f: int(i) for f, i in fi},
    }


def train():
    SAVED_DIR.mkdir(exist_ok=True)

    print("[TRAIN] Đọc features_5m.csv...")
    df = load_labeled_data()
    print(f"[TRAIN] Total rows: {len(df)}")

    all_metrics = {"long": {}, "short": {}}

    for direction in ("long", "short"):
        for h in HORIZONS:
            lc = _label_col(direction, h)
            try:
                metrics = _train_one(df, lc, direction, h)
                if metrics:
                    all_metrics[direction][f"{h}m"] = metrics
            except Exception as e:
                print(f"[TRAIN] ❌ {direction}/{h}m thất bại: {e}")

    long_30m  = all_metrics["long"].get("30m")
    short_30m = all_metrics["short"].get("30m")

    if not any(all_metrics["long"].values()) and not any(all_metrics["short"].values()):
        return

    meta = {
        "model_type":       "LightGBM",
        "feature_cols":     FEATURE_COLS,
        "signal_threshold": SIGNAL_THRESHOLD,
        "trained_at":       pd.Timestamp.now(tz="UTC").isoformat(),
        "horizons":         all_metrics,
        # backward compat: long/short = 30m metrics
        "long":             long_30m,
        "short":            short_30m,
        **(long_30m or {}),
    }

    with open(SAVED_DIR / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[TRAIN] ✅ meta.json saved → {SAVED_DIR}/meta.json")
    trained = sum(1 for d in all_metrics.values() for v in d.values() if v)
    print(f"[TRAIN] ✅ Trained {trained}/12 models")


if __name__ == "__main__":
    train()
