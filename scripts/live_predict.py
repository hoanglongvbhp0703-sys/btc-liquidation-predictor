#!/usr/bin/env python3
"""
scripts/live_predict.py

Real-time prediction display — cập nhật mỗi khi features_1m.csv có row mới.
Hiển thị prob SHORT/LONG cho 1m/2m/3m, lịch sử signals, thống kê session.

Chạy: .venv/bin/python scripts/live_predict.py
Dừng: Ctrl+C
"""

import sys, time, pickle, json, warnings
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.train import FEATURE_COLS, prepare_features
from config import ML_DIR, FEATURES_FILE, SIGNAL_THRESHOLD, HORIZONS

REFRESH_SEC = 5   # poll interval — hiển thị ngay khi có row mới

# ── ANSI colours ──────────────────────────────────────────────────
_R  = "\033[31m"; _G  = "\033[32m"; _Y  = "\033[33m"
_B  = "\033[34m"; _C  = "\033[36m"; _W  = "\033[37m"
_BLD = "\033[1m"; _RST = "\033[0m"
_CLR = "\033[H\033[2J"


def _bar(prob: float, width: int = 20) -> str:
    filled = int(prob * width)
    bar    = "█" * filled + "░" * (width - filled)
    if prob >= SIGNAL_THRESHOLD:
        colour = _R + _BLD
    elif prob >= SIGNAL_THRESHOLD - 0.10:
        colour = _Y
    else:
        colour = _G
    return f"{colour}{bar}{_RST}"


def _load_models():
    models = {}
    for direction in ("short", "long"):
        models[direction] = {}
        for h in HORIZONS:
            p = ML_DIR / f"ens_cascade_{direction}_{h}m.pkl"
            if p.exists():
                art = pickle.load(open(p, "rb"))
                models[direction][h] = (art["models"][0], art["imputer"])
    meta_path = ML_DIR / "meta.json"
    meta  = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    mtime = meta_path.stat().st_mtime if meta_path.exists() else 0
    return models, meta, mtime


def _predict_row(row: pd.Series, models: dict) -> dict:
    df_row = pd.DataFrame([row])
    X_raw  = prepare_features(df_row).values.astype(float)
    probs  = {}
    for direction, hmodels in models.items():
        probs[direction] = {}
        for h, (rf, imp) in hmodels.items():
            probs[direction][h] = float(rf.predict_proba(imp.transform(X_raw))[0][1])
    return probs


def _signal_str(probs: dict, direction: str) -> str:
    max_p = max(probs[direction].values()) if probs[direction] else 0
    if max_p >= SIGNAL_THRESHOLD:
        return f"{_R}{_BLD}🔴 SIGNAL  {max_p:.3f}{_RST}"
    return f"{_W}no signal {max_p:.3f}{_RST}"


def _display(row: pd.Series, probs: dict, meta: dict,
             history: list, model_reloads: int, rows_seen: int):
    now_str     = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    ts_str      = str(row["timestamp"])[:19]
    price       = row.get("current_price", "?")
    trained_at  = meta.get("trained_at", "N/A")[:16]
    avg_auc     = meta.get("avg_auc_test", "N/A")
    imb         = row.get("imbalance_now", float("nan"))
    cvd         = row.get("cvd_delta_1m",  float("nan"))
    liq_total   = row.get("liq_total_1m",  float("nan"))
    funding     = row.get("funding_rate",  float("nan"))

    print(_CLR, end="")
    W = 72

    # ── Header ───────────────────────────────────────────────────
    print(f"{_BLD}{'═'*W}{_RST}")
    print(f"{_BLD}  BTC Live Predict  │  {now_str}  │  model trained {trained_at} UTC{_RST}")
    print(f"  AUC avg={avg_auc}  │  threshold={SIGNAL_THRESHOLD}  │  rows seen={rows_seen}  │  reloads={model_reloads}")
    print(f"{'═'*W}")

    # ── Current market ────────────────────────────────────────────
    imb_str = f"{imb:+.3f}" if not pd.isna(imb) else "?"
    cvd_str = f"{cvd:+.2f}" if not pd.isna(cvd) else "?"
    liq_str = f"${liq_total:,.0f}" if not pd.isna(liq_total) else "?"
    fun_str = f"{funding*100:.4f}%" if not pd.isna(funding) else "?"

    print(f"\n  {_BLD}Price:{_RST} ${price:>10,.1f}   "
          f"Imbalance: {imb_str:>6}   CVD 1m: {cvd_str:>8}")
    print(f"  Liq total 1m: {liq_str:>12}   Funding: {fun_str}")
    print(f"  Feature ts  : {ts_str}")

    # ── Probability bars ──────────────────────────────────────────
    print(f"\n  {_BLD}{'─'*W}{_RST}")
    print(f"  {'Direction':8}  {'Hor':>4}  {'Prob':>6}  {'Bar (threshold →)':32}  Signal?")
    print(f"  {'─'*W}")

    for direction in ("short", "long"):
        d_label  = "SHORT 🔴" if direction == "short" else "LONG  🟢"
        max_p    = max(probs[direction].values()) if probs[direction] else 0
        sig_str  = _signal_str(probs, direction)

        for i, h in enumerate(HORIZONS):
            p    = probs[direction].get(h, 0)
            bar  = _bar(p)
            thr_pos = int(SIGNAL_THRESHOLD * 20)
            thr_mark = " " * thr_pos + f"{_C}│{_RST}"
            if i == 0:
                print(f"  {d_label:9} {h}m   {p:5.3f}  {bar}  {sig_str}")
            else:
                print(f"  {'':9} {h}m   {p:5.3f}  {bar}")

        print()

    # ── Signal history ────────────────────────────────────────────
    print(f"  {'─'*W}")
    if not history:
        print(f"  Chưa có signal trong session này  (threshold={SIGNAL_THRESHOLD})")
    else:
        print(f"  {_BLD}Signals trong session ({len(history)} total):{_RST}")
        for ev in history[-12:]:
            ts   = str(ev["ts"])[:19]
            d    = ev["direction"].upper()
            p    = ev["prob"]
            h    = ev["horizon"]
            icon = "🔴" if d == "SHORT" else "🟢"
            print(f"  {icon} {ts}  {d:5}  prob={p:.3f}  horizon={h}m")

    # ── Session stats ─────────────────────────────────────────────
    print(f"\n  {'─'*W}")
    short_sigs = sum(1 for e in history if e["direction"] == "short")
    long_sigs  = sum(1 for e in history if e["direction"] == "long")
    print(f"  Session: SHORT signals={short_sigs}  LONG signals={long_sigs}  "
          f"rows processed={rows_seen}")
    print(f"{'═'*W}")
    print(f"  Ctrl+C để dừng")


def main():
    print("Loading models...", flush=True)
    models, meta, model_mtime = _load_models()
    model_reloads = 0

    last_ts   = None
    history   = []
    rows_seen = 0

    while True:
        try:
            # Reload model nếu auto_train vừa xong
            meta_path = ML_DIR / "meta.json"
            if meta_path.exists():
                cur_mtime = meta_path.stat().st_mtime
                if cur_mtime != model_mtime:
                    models, meta, model_mtime = _load_models()
                    model_reloads += 1

            # Đọc row mới nhất từ features_1m.csv
            df = pd.read_csv(FEATURES_FILE)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

            if df.empty:
                print("Chờ feature engine build data...", flush=True)
                time.sleep(REFRESH_SEC)
                continue

            latest = df.iloc[-1]
            ts_str = str(latest["timestamp"])

            if ts_str != last_ts:
                last_ts   = ts_str
                rows_seen += 1

                probs = _predict_row(latest, models)

                # Ghi history nếu có signal
                for direction in ("short", "long"):
                    for h in HORIZONS:
                        p = probs[direction].get(h, 0)
                        if p >= SIGNAL_THRESHOLD:
                            max_h = max(probs[direction], key=probs[direction].get)
                            max_p = probs[direction][max_h]
                            already = any(
                                e["ts"] == ts_str and e["direction"] == direction
                                for e in history
                            )
                            if not already:
                                history.append({
                                    "ts":        ts_str,
                                    "direction": direction,
                                    "prob":      round(max_p, 4),
                                    "horizon":   max_h,
                                })
                            break

            _display(latest, probs, meta, history, model_reloads, rows_seen)

        except KeyboardInterrupt:
            print(f"\n\n  Dừng. Session: {len(history)} signals trong {rows_seen} rows.\n")
            break
        except Exception as e:
            print(f"\n[ERR] {e}", flush=True)

        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
