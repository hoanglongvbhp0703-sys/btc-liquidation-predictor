"""
train.py — Tầng 4: Train LightGBM model

Chạy thủ công khi có đủ labeled data:
    python ml/train.py

Output:
    ml/artifacts/lgb_model.pkl   — LightGBM model (pickle)
    ml/artifacts/imputer.pkl     — median imputer (fit trên train)
    ml/artifacts/meta.json       — feature list + training metadata
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping, log_evaluation
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    roc_auc_score, precision_score, recall_score, f1_score,
)

# ─── Paths ─────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
FEATURES_FILE  = BASE_DIR.parent / "data" / "processed" / "features_5m.csv"
SAVED_DIR      = BASE_DIR / "artifacts"
MODEL_FILE     = SAVED_DIR / "lgb_model.pkl"
IMPUTER_FILE   = SAVED_DIR / "imputer.pkl"
META_FILE      = SAVED_DIR / "meta.json"

# ─── Config ────────────────────────────────────────────────────
MIN_ROWS_TO_TRAIN  = 200    # tối thiểu để train; khuyến nghị 2000+
SIGNAL_THRESHOLD   = 0.70   # ngưỡng phát signal
TRAIN_RATIO        = 0.80   # 80% train, 20% test (time-based, không shuffle)
VAL_RATIO_OF_TRAIN = 0.15   # 15% của train dùng cho early stopping

# Features đưa vào model — KHÔNG dùng giá tuyệt đối (current_price, liq_zone_*, oi_now)
# để model không overfit vào price regime cụ thể
FEATURE_COLS = [
    # Giá (relative)
    "price_change_5m", "price_change_1m", "volatility_5m",
    "volume_5m", "taker_buy_ratio",

    # Liquidation
    "liq_long_usd_5m", "liq_short_usd_5m", "liq_total_5m", "liq_ratio_5m",
    "dist_to_upper", "dist_to_lower",

    # Order Book
    "imbalance_now", "imbalance_avg_1m", "imbalance_trend",
    "spread_now", "bid_vol_now", "ask_vol_now", "wall_ratio",

    # CVD + Whale
    "cvd_delta_5m", "cvd_delta_1m",
    "whale_buy_count", "whale_sell_count", "whale_net",
    "whale_buy_usd_5m", "whale_sell_usd_5m", "whale_dominance",

    # Open Interest (delta, không dùng absolute)
    "delta_oi_5m", "delta_oi_30m", "delta_oi_1h", "oi_acceleration",

    # Funding
    "funding_rate", "funding_rate_abs", "funding_bias",
    "funding_long_heavy", "funding_short_heavy",
    "funding_rate_change", "funding_trend_3h",
    "secs_to_next_funding", "funding_urgency",
]


def load_labeled_data() -> pd.DataFrame:
    """Load features_5m.csv, chỉ giữ rows có label 0 hoặc 1."""
    df = pd.read_csv(FEATURES_FILE)
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df[df["label"].isin([0, 1])].copy()
    df["label"] = df["label"].astype(int)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chuyển đổi kiểu dữ liệu và chọn đúng cột FEATURE_COLS.
    Boolean columns (funding_long_heavy, funding_short_heavy) → int.
    """
    X = df[FEATURE_COLS].copy()

    bool_cols = ["funding_long_heavy", "funding_short_heavy"]
    for col in bool_cols:
        if col in X.columns:
            X[col] = X[col].astype(str).map(
                {"True": 1, "False": 0, "1": 1, "0": 0, "1.0": 1, "0.0": 0}
            ).astype(float)

    return X


def time_split(df: pd.DataFrame):
    """Split theo thứ tự thời gian. KHÔNG shuffle để tránh data leakage."""
    n = len(df)
    n_train = int(n * TRAIN_RATIO)

    df_train = df.iloc[:n_train]
    df_test  = df.iloc[n_train:]

    # Validation set: phần cuối của train, dùng cho early stopping
    n_val    = int(n_train * VAL_RATIO_OF_TRAIN)
    df_inner = df_train.iloc[:n_train - n_val]
    df_val   = df_train.iloc[n_train - n_val:]

    return df_inner, df_val, df_test


def train():
    SAVED_DIR.mkdir(exist_ok=True)

    # ── 1. Load data ────────────────────────────────────────────
    print("[TRAIN] Đọc features_5m.csv...")
    df = load_labeled_data()

    n_total    = len(df)
    n_positive = (df["label"] == 1).sum()
    n_negative = (df["label"] == 0).sum()

    pct1 = f"{n_positive/n_total*100:.1f}%" if n_total > 0 else "N/A"
    pct0 = f"{n_negative/n_total*100:.1f}%" if n_total > 0 else "N/A"
    print(f"[TRAIN] Labeled rows : {n_total}")
    print(f"[TRAIN]   label=1    : {n_positive}  ({pct1})")
    print(f"[TRAIN]   label=0    : {n_negative}  ({pct0})")

    if n_total < MIN_ROWS_TO_TRAIN:
        print(f"[TRAIN] ❌ Chưa đủ data. Cần ít nhất {MIN_ROWS_TO_TRAIN} rows (có {n_total}).")
        print(f"[TRAIN]    Khuyến nghị 2,000+ rows để model đáng tin cậy.")
        return

    if n_positive == 0:
        print("[TRAIN] ❌ Không có row label=1. Không thể train.")
        return

    if n_total < 500:
        print(f"[TRAIN] ⚠️  Chỉ có {n_total} rows — model có thể không ổn định. Khuyến nghị 2,000+.")

    # ── 2. Feature prep + split ─────────────────────────────────
    df_inner, df_val, df_test = time_split(df)

    X_inner = prepare_features(df_inner)
    y_inner = df_inner["label"].values
    X_val   = prepare_features(df_val)
    y_val   = df_val["label"].values
    X_test  = prepare_features(df_test)
    y_test  = df_test["label"].values

    print(f"\n[TRAIN] Split (time-based):")
    print(f"  Train inner : {len(X_inner)} rows")
    print(f"  Validation  : {len(X_val)} rows  (early stopping)")
    print(f"  Test        : {len(X_test)} rows")

    # ── 3. Impute NaN (fit trên inner train, transform tất cả) ──
    imputer = SimpleImputer(strategy="median")
    X_inner_imp = imputer.fit_transform(X_inner)
    X_val_imp   = imputer.transform(X_val)
    X_test_imp  = imputer.transform(X_test)

    X_all = prepare_features(df)
    nan_counts = X_all.isna().sum()
    nan_cols   = nan_counts[nan_counts > 0]
    if not nan_cols.empty:
        print(f"\n[TRAIN] NaN đã impute (median):")
        for col, cnt in nan_cols.items():
            print(f"  {col}: {cnt} NaN ({cnt/n_total*100:.1f}%)")

    # ── 4. Train ────────────────────────────────────────────────
    n_neg_inner = (y_inner == 0).sum()
    n_pos_inner = (y_inner == 1).sum()
    spw = n_neg_inner / n_pos_inner if n_pos_inner > 0 else 1.0

    print(f"\n[TRAIN] scale_pos_weight = {spw:.3f}")
    print("[TRAIN] Training LightGBM...")

    model = LGBMClassifier(
        n_estimators     = 500,
        num_leaves       = 31,
        max_depth        = -1,
        learning_rate    = 0.05,
        feature_fraction = 0.8,
        bagging_fraction = 0.8,
        bagging_freq     = 1,
        min_child_samples= 20,
        scale_pos_weight = spw,
        random_state     = 42,
        verbose          = -1,
        n_jobs           = -1,
    )

    model.fit(
        X_inner_imp, y_inner,
        eval_set=[(X_val_imp, y_val)],
        callbacks=[
            early_stopping(stopping_rounds=30, verbose=False),
            log_evaluation(period=-1),
        ],
    )

    best_iter = model.best_iteration_
    print(f"[TRAIN] Best iteration: {best_iter} (của 500 max)")

    # ── 5. Evaluate ─────────────────────────────────────────────
    prob_train = model.predict_proba(X_inner_imp)[:, 1]
    prob_test  = model.predict_proba(X_test_imp)[:, 1]

    auc_train = roc_auc_score(y_inner, prob_train) if len(np.unique(y_inner)) > 1 else float("nan")
    auc_test  = roc_auc_score(y_test,  prob_test)  if len(np.unique(y_test))  > 1 else float("nan")

    print(f"\n[TRAIN] ── AUC ─────────────────────────────")
    print(f"  Train : {auc_train:.4f}")
    print(f"  Test  : {auc_test:.4f}")
    if not (np.isnan(auc_train) or np.isnan(auc_test)) and auc_train - auc_test > 0.10:
        print(f"  ⚠️  Overfit: gap {auc_train - auc_test:.3f} > 0.10")

    # Metrics tại ngưỡng SIGNAL_THRESHOLD
    pred_test = (prob_test >= SIGNAL_THRESHOLD).astype(int)
    n_signals = pred_test.sum()

    if n_signals > 0:
        prec = precision_score(y_test, pred_test, zero_division=0)
        rec  = recall_score(y_test, pred_test, zero_division=0)
        f1   = f1_score(y_test, pred_test, zero_division=0)
    else:
        prec = rec = f1 = 0.0

    print(f"\n[TRAIN] ── @ threshold {SIGNAL_THRESHOLD} ──────────────")
    print(f"  Signals phát ra   : {n_signals}/{len(y_test)} test rows")
    print(f"  Precision         : {prec:.4f}  (trong {n_signals} signals, bao nhiêu đúng)")
    print(f"  Recall            : {rec:.4f}   (bao nhiêu positive thực sự bị bắt)")
    print(f"  F1                : {f1:.4f}")
    if n_signals == 0:
        print(f"  ⚠️  Không có signal nào ở threshold {SIGNAL_THRESHOLD} — thử hạ xuống 0.60?")

    # Feature importance (gain-based)
    importance = model.feature_importances_
    fi = sorted(zip(FEATURE_COLS, importance), key=lambda x: x[1], reverse=True)
    print(f"\n[TRAIN] ── Top 15 Features ─────────────────")
    for i, (feat, imp) in enumerate(fi[:15], 1):
        bar = "█" * int(imp / max(v for _, v in fi) * 30)
        print(f"  {i:2d}. {feat:<30} {imp:6.0f}  {bar}")

    # ── 6. Save ─────────────────────────────────────────────────
    with open(MODEL_FILE, "wb") as f:
        pickle.dump(model, f)

    with open(IMPUTER_FILE, "wb") as f:
        pickle.dump(imputer, f)

    meta = {
        "model_type":        "LightGBM",
        "feature_cols":      FEATURE_COLS,
        "signal_threshold":  SIGNAL_THRESHOLD,
        "n_train":           int(len(X_inner)),
        "n_test":            int(len(X_test)),
        "auc_train":         round(float(auc_train), 4) if not np.isnan(auc_train) else None,
        "auc_test":          round(float(auc_test), 4)  if not np.isnan(auc_test)  else None,
        "precision_at_threshold": round(float(prec), 4),
        "recall_at_threshold":    round(float(rec), 4),
        "f1_at_threshold":        round(float(f1), 4),
        "n_signals_test":    int(n_signals),
        "scale_pos_weight":  round(float(spw), 4),
        "best_iteration":    int(best_iter) if best_iter else None,
        "trained_at":        pd.Timestamp.now(tz="UTC").isoformat(),
        "feature_importance": {f: int(i) for f, i in fi},
    }

    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n[TRAIN] ✅ Model saved → {SAVED_DIR}/")
    print(f"  lgb_model.pkl   ({MODEL_FILE.stat().st_size // 1024} KB)")
    print(f"  imputer.pkl")
    print(f"  meta.json")


if __name__ == "__main__":
    train()
