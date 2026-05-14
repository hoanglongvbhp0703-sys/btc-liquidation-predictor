#!/usr/bin/env python3
"""
scripts/benchmark_models.py

So sánh RF / XGBoost / LightGBM / CatBoost / ExtraTrees trên data hiện tại.
Chạy: .venv/bin/python scripts/benchmark_models.py

Output: bảng AUC + Precision/Recall tại SIGNAL_THRESHOLD cho tất cả models,
        tổng hợp model nào tối ưu nhất.
"""

import sys, time, warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostClassifier

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.train import FEATURE_COLS, prepare_features, load_labeled_data, time_split
from config import SIGNAL_THRESHOLD, HORIZONS

# ── Candidates ────────────────────────────────────────────────────
MODELS = {
    "RandomForest": RandomForestClassifier(
        n_estimators=300, max_depth=10,
        class_weight="balanced", random_state=42, n_jobs=-1,
    ),
    "ExtraTrees": ExtraTreesClassifier(
        n_estimators=300, max_depth=10,
        class_weight="balanced", random_state=42, n_jobs=-1,
    ),
    "XGBoost": xgb.XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        scale_pos_weight=10,   # ~balanced
        use_label_encoder=False, eval_metric="logloss",
        random_state=42, n_jobs=-1, verbosity=0,
    ),
    "LightGBM": lgb.LGBMClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        class_weight="balanced", random_state=42, n_jobs=-1,
        verbose=-1,
    ),
    "CatBoost": CatBoostClassifier(
        iterations=300, depth=6, learning_rate=0.05,
        auto_class_weights="Balanced",
        random_seed=42, verbose=0,
    ),
}


def _eval(name, clf, X_tr, y_tr, X_te, y_te, thr):
    t0 = time.time()
    clf.fit(X_tr, y_tr)
    elapsed = time.time() - t0

    prob = clf.predict_proba(X_te)[:, 1]
    auc  = roc_auc_score(y_te, prob) if len(np.unique(y_te)) > 1 else float("nan")

    pred = (prob >= thr).astype(int)
    n_sig = int(pred.sum())
    prec = precision_score(y_te, pred, zero_division=0)
    rec  = recall_score(y_te,  pred, zero_division=0)
    f1   = f1_score(y_te,      pred, zero_division=0)
    max_p = float(prob.max())

    return {
        "model":    name,
        "auc":      auc,
        "prec":     prec,
        "rec":      rec,
        "f1":       f1,
        "n_sig":    n_sig,
        "max_prob": max_p,
        "sec":      elapsed,
    }


def benchmark_target(df_all, label_col):
    df = df_all.copy()
    df[label_col] = pd.to_numeric(df[label_col], errors="coerce")
    df = df[df[label_col].isin([0, 1])].copy()
    df[label_col] = df[label_col].astype(int)

    if len(df) < 300 or df[label_col].sum() == 0:
        return None

    df_tr, df_te = time_split(df)
    X_tr_raw = prepare_features(df_tr)
    X_te_raw = prepare_features(df_te)
    y_tr = df_tr[label_col].values
    y_te = df_te[label_col].values

    imp = SimpleImputer(strategy="median")
    X_tr = imp.fit_transform(X_tr_raw)
    X_te = imp.transform(X_te_raw)

    n_pos_tr = int(y_tr.sum())
    n_pos_te = int(y_te.sum())

    results = []
    for name, clf in MODELS.items():
        try:
            r = _eval(name, clf, X_tr, y_tr, X_te, y_te, SIGNAL_THRESHOLD)
            results.append(r)
        except Exception as e:
            print(f"  [{name}] lỗi: {e}")

    return results, len(df_tr), len(df_te), n_pos_tr, n_pos_te


def _fmt(v, fmt=".4f"):
    return f"{v:{fmt}}" if not (isinstance(v, float) and np.isnan(v)) else "  N/A "


W = 80

def main():
    print("=" * W)
    print("  BTC Liquidation — Model Benchmark")
    print(f"  Threshold={SIGNAL_THRESHOLD}  |  Horizons={HORIZONS}m")
    print("=" * W)

    print("Loading data...", flush=True)
    df = load_labeled_data()
    print(f"Total rows: {len(df)}\n")

    # Collect per-model avg AUC across all 6 targets
    model_auc_all: dict[str, list] = {n: [] for n in MODELS}

    for direction in ("short", "long"):
        for h in HORIZONS:
            label_col = f"cascade_{direction}_{h}m"
            print(f"{'─'*W}")
            print(f"  TARGET: {label_col.upper()}")

            out = benchmark_target(df, label_col)
            if out is None:
                print("  Không đủ data — bỏ qua.")
                continue

            results, n_tr, n_te, n_pos_tr, n_pos_te = out
            pos_rate = n_pos_te / n_te * 100 if n_te > 0 else 0
            print(f"  Train={n_tr} rows ({n_pos_tr} pos) │ Test={n_te} rows ({n_pos_te} pos, {pos_rate:.1f}%)")
            print()
            print(f"  {'Model':14}  {'AUC':>6}  {'Prec':>6}  {'Rec':>6}  {'F1':>6}  {'Sigs':>5}  {'MaxP':>5}  {'Sec':>5}")
            print(f"  {'─'*70}")

            results.sort(key=lambda r: r["auc"], reverse=True)
            best_auc = results[0]["auc"] if results else 0

            for r in results:
                marker = " ◀" if abs(r["auc"] - best_auc) < 1e-6 else "  "
                print(
                    f"  {r['model']:14}  "
                    f"{_fmt(r['auc'])}"
                    f"  {r['prec']:.4f}"
                    f"  {r['rec']:.4f}"
                    f"  {r['f1']:.4f}"
                    f"  {r['n_sig']:>5}"
                    f"  {r['max_prob']:.3f}"
                    f"  {r['sec']:>4.1f}s"
                    f"{marker}"
                )
                model_auc_all[r["model"]].append(r["auc"])

            print()

    # ── Summary ───────────────────────────────────────────────────
    print("=" * W)
    print("  TỔNG KẾT — Avg AUC qua 6 targets (short+long × 1/2/3m)")
    print(f"  {'─'*40}")

    summary = []
    for name, aucs in model_auc_all.items():
        valid = [a for a in aucs if not np.isnan(a)]
        avg   = np.mean(valid) if valid else float("nan")
        summary.append((name, avg, valid))

    summary.sort(key=lambda x: x[1], reverse=True)

    for rank, (name, avg, aucs_list) in enumerate(summary, 1):
        per = "  ".join(f"{a:.4f}" for a in aucs_list)
        marker = " ★ WINNER" if rank == 1 else ""
        print(f"  #{rank} {name:14}  avg={_fmt(avg)}  [{per}]{marker}")

    print("=" * W)
    winner = summary[0][0] if summary else "N/A"
    print(f"\n  Model tối ưu nhất hiện tại: {winner}")
    print(f"  (dựa trên avg AUC out-of-sample, {len(df)} rows, threshold={SIGNAL_THRESHOLD})")
    print()


if __name__ == "__main__":
    main()
