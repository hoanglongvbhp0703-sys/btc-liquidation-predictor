"""
train.py — Tầng 4: Train cascade liquidation models

Model = Ensemble (RF + LogisticReg + XGBoost) — avg prob của 3 models
  Benchmark 12k rows: Ensemble avg AUC 0.7157 > RF 0.7128 > XGB 0.7041 > LR 0.6919
  SHORT avg AUC 0.735, LONG avg AUC 0.697

Artifacts per target: ens_cascade_{direction}_{h}m.pkl
  chứa {"models": [rf, lr, xgb], "imputer": ..., "scaler": ..., "model_names": [...]}

Output artifacts: ml/artifacts/
"""

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, precision_score, recall_score
import xgboost as xgb

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FEATURES_FILE, ML_DIR, HORIZONS, MIN_ROWS_TRAIN, SIGNAL_THRESHOLD

SAVED_DIR   = ML_DIR
TRAIN_RATIO = 0.80

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
    # Spot CVD + Basis (mới — chỉ có từ khi collector update)
    "spot_cvd_delta_1m", "spot_cvd_delta_30s",
    "basis_pct", "basis_change_1m", "basis_positive",
    "cvd_divergence",
]


def load_labeled_data() -> pd.DataFrame:
    try:
        df = pd.read_csv(FEATURES_FILE)
    except (pd.errors.EmptyDataError, Exception) as e:
        raise RuntimeError(f"[TRAIN] Không đọc được {FEATURES_FILE}: {e}") from e
    if df.empty:
        raise RuntimeError(f"[TRAIN] {FEATURES_FILE} rỗng — bỏ qua lần train này.")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="ISO8601")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURE_COLS].copy()
    bool_cols = ("funding_long_heavy", "funding_short_heavy", "basis_positive")
    for col in bool_cols:
        if col in X.columns:
            X[col] = X[col].astype(str).map(
                {"True": 1, "False": 0, "1": 1, "0": 0, "1.0": 1, "0.0": 0}
            ).astype(float)
    return X


def time_split(df: pd.DataFrame):
    n_train = int(len(df) * TRAIN_RATIO)
    return df.iloc[:n_train], df.iloc[n_train:]


# ── Model: Ensemble (RF + LogisticReg + XGBoost) ─────────────────

def _train_classifier(df_all: pd.DataFrame, label_col: str, direction: str, horizon: int) -> dict | None:
    if label_col not in df_all.columns:
        print(f"[TRAIN] {direction}/{horizon}m: cột '{label_col}' chưa có — bỏ qua.")
        return None

    df = df_all.copy()
    df[label_col] = pd.to_numeric(df[label_col], errors="coerce")
    df = df[df[label_col].isin([0, 1])].copy()
    df[label_col] = df[label_col].astype(int)

    n_total    = len(df)
    n_positive = (df[label_col] == 1).sum()
    pct1 = f"{n_positive/n_total*100:.1f}%" if n_total > 0 else "N/A"

    print(f"\n[TRAIN] ── cascade_{direction} {horizon}m ──────────────────────")
    print(f"[TRAIN]   Rows: {n_total}  pos={n_positive} ({pct1})")

    if n_total < MIN_ROWS_TRAIN:
        print(f"[TRAIN]   Cần ít nhất {MIN_ROWS_TRAIN} rows. Bỏ qua.")
        return None
    if n_positive == 0:
        print(f"[TRAIN]   Không có label=1. Bỏ qua.")
        return None

    df_inner, df_test = time_split(df)

    X_inner = prepare_features(df_inner)
    X_test  = prepare_features(df_test)
    y_inner = df_inner[label_col].values
    y_test  = df_test[label_col].values

    imputer = SimpleImputer(strategy="median")
    X_inner_imp = imputer.fit_transform(X_inner)
    X_test_imp  = imputer.transform(X_test)

    scaler = StandardScaler()
    X_inner_sc = scaler.fit_transform(X_inner_imp)
    X_test_sc  = scaler.transform(X_test_imp)

    spw = float((y_inner == 0).sum()) / max((y_inner == 1).sum(), 1)

    rf = RandomForestClassifier(
        n_estimators=300, max_depth=10, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    rf.fit(X_inner_imp, y_inner)

    lr = LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)
    lr.fit(X_inner_sc, y_inner)

    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        scale_pos_weight=spw,
        eval_metric="logloss", random_state=42, n_jobs=-1,
        device="cpu", verbosity=0,
    )
    xgb_model.fit(X_inner_imp, y_inner)

    # Ensemble: avg prob RF + LR + XGB
    p_rf  = rf.predict_proba(X_test_imp)[:, 1]
    p_lr  = lr.predict_proba(X_test_sc)[:, 1]
    p_xgb = xgb_model.predict_proba(X_test_imp)[:, 1]
    prob_test = (p_rf + p_lr + p_xgb) / 3

    auc_test  = roc_auc_score(y_test, prob_test) if len(np.unique(y_test)) > 1 else float("nan")
    auc_rf    = roc_auc_score(y_test, p_rf)  if len(np.unique(y_test)) > 1 else float("nan")
    auc_lr    = roc_auc_score(y_test, p_lr)  if len(np.unique(y_test)) > 1 else float("nan")
    auc_xgb   = roc_auc_score(y_test, p_xgb) if len(np.unique(y_test)) > 1 else float("nan")

    pred_test = (prob_test >= SIGNAL_THRESHOLD).astype(int)
    n_signals = int(pred_test.sum())
    prec = precision_score(y_test, pred_test, zero_division=0) if n_signals > 0 else 0.0
    rec  = recall_score(y_test, pred_test, zero_division=0)    if n_signals > 0 else 0.0

    print(f"[TRAIN]   AUC ens={auc_test:.4f}  rf={auc_rf:.4f}  lr={auc_lr:.4f}  xgb={auc_xgb:.4f}")
    print(f"[TRAIN]   max_prob={prob_test.max():.3f}  @{SIGNAL_THRESHOLD}: signals={n_signals} prec={prec:.3f} rec={rec:.3f}")

    suffix   = f"cascade_{direction}_{horizon}m"
    ens_file = SAVED_DIR / f"ens_{suffix}.pkl"
    artifact = {
        "models":      [rf, lr, xgb_model],
        "imputer":     imputer,
        "scaler":      scaler,
        "model_names": ["RandomForest", "LogisticReg", "XGBoost"],
    }
    with open(ens_file, "wb") as f:
        pickle.dump(artifact, f)

    print(f"[TRAIN]   Saved → {ens_file.name}")

    return {
        "n_train":        int(len(X_inner)),
        "n_test":         int(len(X_test)),
        "auc_test":       round(float(auc_test), 4) if not np.isnan(auc_test) else None,
        "auc_rf":         round(float(auc_rf),   4) if not np.isnan(auc_rf)   else None,
        "auc_lr":         round(float(auc_lr),   4) if not np.isnan(auc_lr)   else None,
        "auc_xgb":        round(float(auc_xgb),  4) if not np.isnan(auc_xgb)  else None,
        "max_prob":       round(float(prob_test.max()), 4),
        "precision":      round(float(prec), 4),
        "recall":         round(float(rec),  4),
        "n_signals_test": n_signals,
    }


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
        "model_type":       "Ensemble_RF+LR+XGB cascade",
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
