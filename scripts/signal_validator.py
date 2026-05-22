#!/usr/bin/env python3
"""
scripts/signal_validator.py

Chạy 24/7 — bắt signal và xem có cascade thật không.
Mỗi phút:
  1. Đọc row mới từ features_1m.csv
  2. Inference → nếu prob >= threshold → ghi PENDING signal
  3. Với PENDING signals đã qua đủ horizon+2 phút → tra label thật → ghi TP/FP

Kết quả lưu vào: data/signal_outcomes.csv  (persist qua restart)
Chạy: .venv/bin/python scripts/signal_validator.py
Dừng: Ctrl+C
"""

import sys, time, pickle, json, warnings
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ml.train import FEATURE_COLS, prepare_features
from config import ML_DIR, FEATURES_FILE, DATA_DIR, SIGNAL_THRESHOLD, HORIZONS

OUTCOMES_FILE = DATA_DIR / "signal_outcomes.csv"
REFRESH_SEC   = 60   # check mỗi 1 phút (sync với feature_engine)
RESOLVE_DELAY = 2    # chờ thêm N phút sau horizon trước khi check label

OUTCOME_COLS = [
    "signal_ts", "direction", "horizon", "max_prob",
    "prob_1m", "prob_2m", "prob_3m",
    "price", "outcome", "cascade_label", "resolved_ts",
]

_R = "\033[31m"; _G = "\033[32m"; _Y = "\033[33m"
_C = "\033[36m"; _W = "\033[37m"; _BLD = "\033[1m"; _RST = "\033[0m"
_CLR = "\033[H\033[2J"


# ── Model loading ─────────────────────────────────────────────────

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


# ── Outcomes file ─────────────────────────────────────────────────

def _load_outcomes() -> pd.DataFrame:
    if OUTCOMES_FILE.exists() and OUTCOMES_FILE.stat().st_size > 0:
        df = pd.read_csv(OUTCOMES_FILE)
        for col in OUTCOME_COLS:
            if col not in df.columns:
                df[col] = None
        return df[OUTCOME_COLS]
    return pd.DataFrame(columns=OUTCOME_COLS)


def _save_outcomes(df: pd.DataFrame):
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(OUTCOMES_FILE, index=False)


# ── Resolve pending signals ────────────────────────────────────────

def _resolve_pending(outcomes: pd.DataFrame, features_df: pd.DataFrame) -> pd.DataFrame:
    pending_idx = outcomes.index[outcomes["outcome"] == "PENDING"]
    if len(pending_idx) == 0:
        return outcomes

    now = pd.Timestamp.now(tz="UTC")
    feat_ts = pd.to_datetime(features_df["timestamp"], utc=True, errors="coerce", format="ISO8601")

    for idx in pending_idx:
        row      = outcomes.loc[idx]
        sig_ts   = pd.to_datetime(row["signal_ts"], utc=True)
        h        = int(row["horizon"])
        direction = row["direction"]
        label_col = f"cascade_{direction}_{h}m"

        # Chưa đủ thời gian để label được điền
        if now < sig_ts + timedelta(minutes=h + RESOLVE_DELAY):
            continue

        # Tìm row features khớp timestamp
        diff  = (feat_ts - sig_ts).abs()
        close = features_df[diff <= pd.Timedelta("30s")]
        if close.empty:
            continue

        feat_row = close.iloc[0]
        if label_col not in features_df.columns:
            continue

        label_val = feat_row.get(label_col, None)
        if pd.isna(label_val):
            continue

        label_int = int(float(label_val))
        outcomes.loc[idx, "cascade_label"] = label_int
        outcomes.loc[idx, "outcome"]        = "TP" if label_int == 1 else "FP"
        outcomes.loc[idx, "resolved_ts"]    = now.isoformat()

    return outcomes


# ── Display ───────────────────────────────────────────────────────

def _bar(prob: float, width: int = 20) -> str:
    filled = int(prob * width)
    bar    = "█" * filled + "░" * (width - filled)
    if prob >= SIGNAL_THRESHOLD:
        return f"{_R}{_BLD}{bar}{_RST}"
    elif prob >= SIGNAL_THRESHOLD - 0.10:
        return f"{_Y}{bar}{_RST}"
    return f"{_G}{bar}{_RST}"


def _outcome_str(out: str) -> str:
    if out == "TP":
        return f"{_G}{_BLD}TP ✓   {_RST}"
    if out == "FP":
        return f"{_R}FP ✗   {_RST}"
    return f"{_Y}PENDING{_RST}"


def _display(row, probs, meta, outcomes: pd.DataFrame,
             model_reloads: int, rows_seen: int, start_time: datetime):
    now     = datetime.now(timezone.utc)
    elapsed = now - start_time
    days    = elapsed.days
    hours   = elapsed.seconds // 3600
    mins    = (elapsed.seconds % 3600) // 60

    now_str     = now.strftime("%H:%M:%S UTC")
    ts_str      = str(row["timestamp"])[:19]
    avg_auc     = meta.get("avg_auc_test", "N/A")
    trained_at  = meta.get("trained_at", "N/A")[:16]

    try:
        price = float(row.get("current_price", row.get("mid_price_now", 0)))
        price_str = f"${price:>10,.1f}"
    except Exception:
        price_str = "?"

    imb = row.get("imbalance_now", float("nan"))
    cvd = row.get("cvd_delta_1m",  float("nan"))
    imb_str = f"{imb:+.3f}" if not pd.isna(imb) else "?"
    cvd_str = f"{cvd:+.2f}" if not pd.isna(cvd) else "?"

    print(_CLR, end="")
    W = 76

    # Header
    print(f"{_BLD}{'═'*W}{_RST}")
    print(f"{_BLD}  BTC Signal Validator  │  {now_str}  │  Uptime {days}d {hours:02d}h {mins:02d}m{_RST}")
    print(f"  AUC={avg_auc}  thr={SIGNAL_THRESHOLD}  trained={trained_at}  reloads={model_reloads}  rows={rows_seen}")
    print(f"{'═'*W}")

    # Market snapshot
    print(f"\n  {_BLD}Price:{_RST} {price_str}   Imbalance: {imb_str:>7}   CVD 1m: {cvd_str:>9}")
    print(f"  Feature ts: {ts_str}")

    # Probabilities
    print(f"\n  {'─'*W}")
    print(f"  {'Dir':7}  {'H':>2}  {'Prob':>5}  {'Bar':22}  Signal?")
    print(f"  {'─'*W}")

    for direction in ("short", "long"):
        icon = "🔴" if direction == "short" else "🟢"
        label = "SHORT" if direction == "short" else "LONG "
        for i, h in enumerate(HORIZONS):
            p   = probs[direction].get(h, 0)
            bar = _bar(p)
            sig = f"{_R}{_BLD}◀ SIGNAL{_RST}" if p >= SIGNAL_THRESHOLD else ""
            prefix = f"{icon}{label}" if i == 0 else "      "
            print(f"  {prefix}  {h}m  {p:.3f}  {bar}  {sig}")
        print()

    # Stats
    total    = len(outcomes)
    pending  = int((outcomes["outcome"] == "PENDING").sum())
    tp_all   = int((outcomes["outcome"] == "TP").sum())
    fp_all   = int((outcomes["outcome"] == "FP").sum())
    resolved = tp_all + fp_all

    print(f"  {'─'*W}")
    print(f"  {_BLD}Signal Outcomes  total={total}  TP={tp_all}  FP={fp_all}  PENDING={pending}{_RST}")

    for d in ("short", "long"):
        icon   = "🔴" if d == "short" else "🟢"
        mask   = outcomes["direction"] == d
        d_tp   = int(((outcomes["outcome"] == "TP") & mask).sum())
        d_fp   = int(((outcomes["outcome"] == "FP") & mask).sum())
        d_pend = int(((outcomes["outcome"] == "PENDING") & mask).sum())
        d_res  = d_tp + d_fp
        d_prec = d_tp / d_res if d_res > 0 else 0
        prec_str = f"{d_prec:.1%}" if d_res > 0 else "N/A"
        print(f"  {icon} {d.upper():5}  signals={d_tp+d_fp+d_pend}  "
              f"TP={d_tp}  FP={d_fp}  PENDING={d_pend}  Precision={prec_str}")

    if resolved > 0:
        prec_overall = tp_all / resolved
        print(f"\n  Overall precision (resolved): {_BLD}{prec_overall:.1%}{_RST}  ({tp_all}/{resolved})")

    # Recent signals table
    if total > 0:
        print(f"\n  {'─'*W}")
        print(f"  {'Timestamp':19}  {'Dir':5}  {'H':>2}  {'Prob':>5}  {'Price':>11}  {'Outcome':9}  Label")
        print(f"  {'─'*W}")
        recent = outcomes.tail(18).iloc[::-1]
        for _, ev in recent.iterrows():
            ts   = str(ev["signal_ts"])[:19]
            d    = str(ev["direction"]).upper()
            h    = ev["horizon"]
            prob = float(ev["max_prob"]) if not pd.isna(ev["max_prob"]) else 0
            try:
                p_str = f"${float(ev['price']):>10,.1f}"
            except Exception:
                p_str = f"{'?':>11}"
            out_s  = _outcome_str(str(ev["outcome"]))
            lbl    = str(int(float(ev["cascade_label"]))) if not pd.isna(ev.get("cascade_label", float("nan"))) else "?"
            icon   = "🔴" if d == "SHORT" else "🟢"
            print(f"  {icon} {ts}  {d:5}  {h:>2}  {prob:.3f}  {p_str}  {out_s}  {lbl}")
    else:
        print(f"\n  Chưa có signal nào — đang chờ prob >= {SIGNAL_THRESHOLD}...")

    print(f"\n{'═'*W}")
    print(f"  Outcomes → {OUTCOMES_FILE.name}  │  Ctrl+C để dừng")


# ── Main ──────────────────────────────────────────────────────────

def main():
    print("Loading models...", flush=True)
    models, meta, model_mtime = _load_models()
    model_reloads = 0
    start_time    = datetime.now(timezone.utc)

    outcomes  = _load_outcomes()
    last_ts   = None
    rows_seen = 0
    last_probs = {d: {h: 0.0 for h in HORIZONS} for d in ("short", "long")}
    last_row   = None

    print(f"Loaded {len(outcomes)} existing outcomes from {OUTCOMES_FILE}", flush=True)
    print("Running — refresh every 60s...", flush=True)

    while True:
        try:
            # Reload model khi auto_train vừa xong
            meta_path = ML_DIR / "meta.json"
            if meta_path.exists():
                cur_mtime = meta_path.stat().st_mtime
                if cur_mtime != model_mtime:
                    models, meta, model_mtime = _load_models()
                    model_reloads += 1

            # Đọc features
            df = pd.read_csv(FEATURES_FILE)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce", format="ISO8601")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

            if df.empty:
                print("Waiting for feature data...", flush=True)
                time.sleep(REFRESH_SEC)
                continue

            # Resolve pending outcomes
            outcomes = _resolve_pending(outcomes, df)

            latest = df.iloc[-1]
            ts_str = str(latest["timestamp"])

            if ts_str != last_ts:
                last_ts    = ts_str
                rows_seen += 1
                last_probs = _predict_row(latest, models)
                last_row   = latest

                try:
                    price = float(latest.get("current_price", latest.get("mid_price_now", 0)))
                except Exception:
                    price = None

                # Ghi signal nếu có
                save_needed = False
                for direction in ("short", "long"):
                    if not last_probs[direction]:
                        continue
                    max_h = max(last_probs[direction], key=last_probs[direction].get)
                    max_p = last_probs[direction][max_h]

                    if max_p >= SIGNAL_THRESHOLD:
                        ts_key = ts_str[:19]
                        already = (
                            (outcomes["signal_ts"].astype(str).str[:19] == ts_key) &
                            (outcomes["direction"] == direction)
                        ).any()
                        if not already:
                            new_row = {
                                "signal_ts":     ts_str,
                                "direction":     direction,
                                "horizon":       max_h,
                                "max_prob":      round(max_p, 4),
                                "prob_1m":       round(last_probs[direction].get(1, 0), 4),
                                "prob_2m":       round(last_probs[direction].get(2, 0), 4),
                                "prob_3m":       round(last_probs[direction].get(3, 0), 4),
                                "price":         round(price, 2) if price else None,
                                "outcome":       "PENDING",
                                "cascade_label": None,
                                "resolved_ts":   None,
                            }
                            outcomes    = pd.concat(
                                [outcomes, pd.DataFrame([new_row])],
                                ignore_index=True,
                            )
                            save_needed = True

                if save_needed:
                    _save_outcomes(outcomes)

            if last_row is not None:
                _display(last_row, last_probs, meta, outcomes,
                         model_reloads, rows_seen, start_time)

        except KeyboardInterrupt:
            _save_outcomes(outcomes)
            total   = len(outcomes)
            tp      = int((outcomes["outcome"] == "TP").sum())
            fp      = int((outcomes["outcome"] == "FP").sum())
            pending = int((outcomes["outcome"] == "PENDING").sum())
            print(f"\n\n  Dừng. Outcomes: total={total} TP={tp} FP={fp} PENDING={pending}")
            print(f"  Saved → {OUTCOMES_FILE}\n")
            break
        except Exception as e:
            print(f"\n[ERR] {e}", flush=True)
            import traceback; traceback.print_exc()

        time.sleep(REFRESH_SEC)


if __name__ == "__main__":
    main()
