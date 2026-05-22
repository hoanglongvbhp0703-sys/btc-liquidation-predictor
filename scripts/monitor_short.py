#!/usr/bin/env python3
"""
scripts/monitor_short.py

Theo dõi độ chính xác SHORT signal real-time.

Logic:
  Mỗi 60s đọc features_1m.csv, score tất cả rows đã có label.
  Phân loại từng row:
    TP — model báo signal  VÀ  cascade thực xảy ra
    FP — model báo signal  nhưng  cascade KHÔNG xảy ra
    FN — cascade thực xảy ra  nhưng  model KHÔNG báo
  Bảng events + thống kê in lại sau mỗi lần refresh.
  Tự reload model ngay khi auto_train ghi xong meta.json.

Chạy trong tmux:
  tmux new-window -t btc -n monitor \
    "cd /home/coder && .venv/bin/python scripts/monitor_short.py"
Dừng: Ctrl+C
"""

import os
import sys
import time
import pickle
import json
import warnings
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.train import FEATURE_COLS, prepare_features
from config import FEATURES_FILE, SIGNAL_THRESHOLD, ML_DIR, HORIZONS

ARTIFACTS_DIR = ML_DIR
THRESHOLD     = SIGNAL_THRESHOLD
REFRESH_SEC   = 60


# ── Model ─────────────────────────────────────────────────────────

def _load_models():
    models = {}
    for h in HORIZONS:
        path = ARTIFACTS_DIR / f"ens_cascade_short_{h}m.pkl"
        if path.exists():
            art = pickle.load(open(path, "rb"))
            models[h] = (art["models"][0], art["imputer"])
    meta_path = ARTIFACTS_DIR / "meta.json"
    meta  = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    mtime = meta_path.stat().st_mtime if meta_path.exists() else 0
    return models, meta, mtime


def _batch_score(df_rows: pd.DataFrame, models: dict) -> pd.DataFrame:
    """Score nhiều rows cùng lúc. Thêm cột prob_1m/2m/3m vào df_rows."""
    df = df_rows.copy()
    X_raw = prepare_features(df).values.astype(float)
    for h, (rf, imp) in models.items():
        X_imp = imp.transform(X_raw)
        df[f"prob_{h}m"] = rf.predict_proba(X_imp)[:, 1]
    return df


# ── Display ───────────────────────────────────────────────────────

_RESULT_ICON = {"TP": "✅ TP", "FP": "❌ FP", "FN": "🔕 FN"}
_W = 92


def _clear():
    print("\033[H\033[2J", end="", flush=True)


def _display(events: list, meta: dict, n_seen: int, model_reloads: int):
    _clear()
    trained_at = meta.get("trained_at", "N/A")[:19]
    avg_auc    = meta.get("avg_auc_test", "N/A")
    mtype      = meta.get("model_type", "?")
    now_str    = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    print("═" * _W)
    print(f"  SHORT Signal Monitor  │  {mtype}  │  Trained: {trained_at}  │  AUC: {avg_auc}")
    print(f"  Threshold: {THRESHOLD}  │  Rows processed: {n_seen}  │  Model reloads: {model_reloads}  │  {now_str}")
    print("═" * _W)

    if not events:
        print("\n  Đang chờ events (actual cascade=1 hoặc model signal ≥ 0.70)...\n")
        _print_stats(events)
        print("═" * _W)
        return

    # Bảng events
    hdr = f"  {'Timestamp':19s}  {'P1m':>5} {'P2m':>5} {'P3m':>5}  {'Signal':>6}  {'Act1m':>5} {'Act2m':>5} {'Act3m':>5}  Kết quả"
    print(f"\n{hdr}")
    print("  " + "─" * (_W - 2))

    for ev in events[-25:]:
        ts   = str(ev["ts"])[:19]
        p1   = f"{ev['p1']:.3f}"
        p2   = f"{ev['p2']:.3f}"
        p3   = f"{ev['p3']:.3f}"
        sig  = "YES" if ev["signal"] else "no"
        a1   = str(ev["a1"]) if ev["a1"] is not None else "?"
        a2   = str(ev["a2"]) if ev["a2"] is not None else "?"
        a3   = str(ev["a3"]) if ev["a3"] is not None else "?"
        icon = _RESULT_ICON.get(ev["result"], "")
        print(f"  {ts:19s}  {p1:>5} {p2:>5} {p3:>5}  {sig:>6}  {a1:>5} {a2:>5} {a3:>5}  {icon}")

    print()
    _print_stats(events)
    print("═" * _W)


def _print_stats(events: list):
    tp = sum(1 for e in events if e["result"] == "TP")
    fp = sum(1 for e in events if e["result"] == "FP")
    fn = sum(1 for e in events if e["result"] == "FN")
    signals = tp + fp
    actuals = tp + fn
    prec = tp / signals * 100 if signals > 0 else 0.0
    rec  = tp / actuals * 100 if actuals > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    print("  " + "─" * 50)
    print(f"  Signals fired   : {signals:>4}  (TP={tp}  FP={fp})")
    print(f"  Actual cascades : {actuals:>4}  (TP={tp}  FN={fn})")
    print(f"  Precision       : {prec:>5.1f}%")
    print(f"  Recall          : {rec:>5.1f}%")
    print(f"  F1              : {f1:>5.1f}%")


# ── Main ──────────────────────────────────────────────────────────

def main():
    models, meta, model_mtime = _load_models()
    model_reloads = 0
    seen_ts = set()
    events  = []

    print("Đang load models và đọc data lịch sử...", flush=True)

    while True:
        try:
            # Kiểm tra model mới (auto_train ghi meta.json)
            meta_path = ARTIFACTS_DIR / "meta.json"
            if meta_path.exists():
                cur_mtime = meta_path.stat().st_mtime
                if cur_mtime != model_mtime:
                    models, meta, model_mtime = _load_models()
                    model_reloads += 1

            # Đọc features
            df = pd.read_csv(FEATURES_FILE)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="ISO8601")
            for h in HORIZONS:
                df[f"cascade_short_{h}m"] = pd.to_numeric(
                    df[f"cascade_short_{h}m"], errors="coerce"
                )

            # Chỉ lấy rows đã labeled (cascade_short_1m phải là 0 hoặc 1)
            df_labeled = df[df["cascade_short_1m"].isin([0, 1])].copy()

            # Rows chưa xử lý
            ts_series  = df_labeled["timestamp"].astype(str)
            new_mask   = ~ts_series.isin(seen_ts)
            new_rows   = df_labeled[new_mask].copy()

            if not new_rows.empty and models:
                scored = _batch_score(new_rows, models)

                for _, row in scored.iterrows():
                    ts_key = str(row["timestamp"])
                    seen_ts.add(ts_key)

                    p1 = float(row.get("prob_1m", 0) or 0)
                    p2 = float(row.get("prob_2m", 0) or 0)
                    p3 = float(row.get("prob_3m", 0) or 0)
                    max_prob = max(p1, p2, p3)
                    signal   = max_prob >= THRESHOLD

                    a1 = int(row["cascade_short_1m"]) if not pd.isna(row["cascade_short_1m"]) else None
                    a2 = int(row["cascade_short_2m"]) if not pd.isna(row.get("cascade_short_2m", float("nan"))) else None
                    a3 = int(row["cascade_short_3m"]) if not pd.isna(row.get("cascade_short_3m", float("nan"))) else None
                    any_actual = a1 == 1 or a2 == 1 or a3 == 1

                    # Chỉ ghi event nếu có gì đáng chú ý
                    if not signal and not any_actual:
                        continue

                    if   signal and any_actual:  result = "TP"
                    elif signal and not any_actual: result = "FP"
                    else:                         result = "FN"

                    events.append({
                        "ts": row["timestamp"], "p1": p1, "p2": p2, "p3": p3,
                        "signal": signal, "a1": a1, "a2": a2, "a3": a3,
                        "result": result,
                    })

            events.sort(key=lambda e: e["ts"])
            _display(events, meta, len(seen_ts), model_reloads)

        except KeyboardInterrupt:
            print("\n\n  Monitor dừng.")
            break
        except Exception as e:
            print(f"\n  [ERR] {e}", flush=True)

        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
