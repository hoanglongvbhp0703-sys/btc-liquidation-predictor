"""
Rebuild features_1m.csv từ historical raw data.
Load tất cả CSVs 1 lần → loop qua timestamps → slice in-memory → write.
Bỏ qua timestamps đã có trong features file.
"""
import sys, csv, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "feature_engine"))
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np
from datetime import timedelta

from build_features import FEATURE_COLUMNS
from feat_price         import compute_price_features
from feat_liquidation   import compute_liquidation_features
from feat_orderbook     import compute_orderbook_features
from feat_aggtrade      import compute_aggtrade_features
from feat_oi            import compute_oi_features
from feat_funding       import compute_funding_features
from config import DATA_DIR, FEATURES_FILE

# ── Optional spot/basis (graceful if missing) ──────────────────────
try:
    from feat_spot_aggtrade import compute_spot_aggtrade_features
    from feat_basis         import compute_basis_features
    from config import SPOT_AGGTRADE_FILE, PREMIUM_INDEX_FILE, BASIS_FILE
    HAS_SPOT = True
except Exception:
    HAS_SPOT = False

# ── Load all raw data once ─────────────────────────────────────────
print("Loading raw data...")
t0 = time.time()

klines = pd.read_csv(DATA_DIR / "klines_1s.csv")
klines["open_time"] = pd.to_datetime(klines["open_time"], format="ISO8601", utc=True, errors="coerce")
klines = klines.dropna(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
print(f"  klines: {len(klines)} rows")

liqs = pd.read_csv(DATA_DIR / "liquidations.csv")
liqs["event_time"] = pd.to_datetime(liqs["event_time"], format="ISO8601", utc=True, errors="coerce")
liqs = liqs.dropna(subset=["event_time"]).sort_values("event_time").reset_index(drop=True)
print(f"  liquidations: {len(liqs)} rows")

ob = pd.read_csv(DATA_DIR / "orderbook.csv")
ob["timestamp"] = pd.to_datetime(ob["timestamp"], format="ISO8601", utc=True, errors="coerce")
ob = ob.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
print(f"  orderbook: {len(ob)} rows")

agg = pd.read_csv(DATA_DIR / "aggtrades.csv")
agg["timestamp"] = pd.to_datetime(agg["timestamp"], format="ISO8601", utc=True, errors="coerce")
agg = agg.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
print(f"  aggtrades: {len(agg)} rows")

oi = pd.read_csv(DATA_DIR / "open_interest.csv")
oi["timestamp"] = pd.to_datetime(oi["timestamp"], format="ISO8601", utc=True, errors="coerce")
oi = oi.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
print(f"  open_interest: {len(oi)} rows")

# Đọc premium_index.csv nếu có (mới), fallback về funding_rate.csv (cũ)
if HAS_SPOT and PREMIUM_INDEX_FILE.exists() and PREMIUM_INDEX_FILE.stat().st_size > 100:
    funding = pd.read_csv(PREMIUM_INDEX_FILE)
    funding["timestamp"] = pd.to_datetime(funding["timestamp"], format="ISO8601", utc=True, errors="coerce")
    funding = funding.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    print(f"  premium_index: {len(funding)} rows")
    basis = funding  # premium_index chứa cả basis_pct
else:
    funding = pd.read_csv(DATA_DIR / "funding_rate.csv")
    funding["timestamp"] = pd.to_datetime(funding["timestamp"], format="ISO8601", utc=True, errors="coerce")
    funding = funding.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    print(f"  funding_rate: {len(funding)} rows")
    basis = pd.DataFrame()
    if HAS_SPOT and BASIS_FILE.exists():
        basis = pd.read_csv(BASIS_FILE)
        basis["timestamp"] = pd.to_datetime(basis["timestamp"], format="ISO8601", utc=True, errors="coerce")
        basis = basis.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        print(f"  basis: {len(basis)} rows")

if HAS_SPOT:
    spot_agg = pd.read_csv(SPOT_AGGTRADE_FILE)
    spot_agg["timestamp"] = pd.to_datetime(spot_agg["timestamp"], format="ISO8601", utc=True, errors="coerce")
    spot_agg = spot_agg.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    print(f"  spot_aggtrades: {len(spot_agg)} rows")

print(f"Load time: {time.time()-t0:.1f}s")

# ── Check existing timestamps ──────────────────────────────────────
existing_ts = set()
if FEATURES_FILE.exists() and FEATURES_FILE.stat().st_size > 0:
    try:
        existing = pd.read_csv(FEATURES_FILE, usecols=["timestamp"])
        existing_ts = set(existing["timestamp"].astype(str).tolist())
        print(f"Existing rows to skip: {len(existing_ts)}")
    except Exception as e:
        print(f"Warning: can't read existing features: {e}")

# ── Timestamps to build ────────────────────────────────────────────
# Start from earliest kline data, end 5 min before now (to ensure some label data available)
data_start = klines["open_time"].min().ceil("1min")
data_end   = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=5)
data_end   = data_end.floor("1min")

timestamps = pd.date_range(start=data_start, end=data_end, freq="1min")
to_build   = [ts for ts in timestamps if ts.isoformat() not in existing_ts]
print(f"\nTimestamps: {len(timestamps)} total | {len(to_build)} to build")

# ── Build features ─────────────────────────────────────────────────
def slice_1m(df, col, t_end, minutes=1):
    t_start = t_end - timedelta(minutes=minutes)
    return df[(df[col] >= t_start) & (df[col] < t_end)]

def slice_4h(df, col, t_end):
    t_start = t_end - timedelta(hours=4)
    return df[(df[col] >= t_start) & (df[col] < t_end)]

written = 0
errors  = 0
t_start = time.time()

# Open file in append mode
with open(FEATURES_FILE, "a", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FEATURE_COLUMNS, extrasaction="ignore")
    if FEATURES_FILE.stat().st_size == 0 or len(existing_ts) == 0:
        writer.writeheader()

    for i, ts in enumerate(to_build):
        try:
            w_klines  = slice_1m(klines,  "open_time",  ts)
            w_liq     = slice_1m(liqs,    "event_time", ts)
            w_ob      = slice_1m(ob,      "timestamp",  ts)
            w_agg     = slice_1m(agg,     "timestamp",  ts)
            w_oi      = slice_4h(oi,      "timestamp",  ts)
            w_funding = slice_4h(funding, "timestamp",  ts)

            row = {"timestamp": ts.isoformat()}
            row.update(compute_price_features(w_klines))
            row.update(compute_liquidation_features(w_liq))
            row.update(compute_orderbook_features(w_ob))
            row.update(compute_aggtrade_features(w_agg))
            row.update(compute_oi_features(w_oi))
            row.update(compute_funding_features(w_funding))

            if HAS_SPOT:
                w_spot  = slice_1m(spot_agg, "timestamp", ts)
                row.update(compute_spot_aggtrade_features(w_spot))
                if not basis.empty:
                    w_basis = slice_4h(basis, "timestamp", ts)
                    row.update(compute_basis_features(w_basis))
                fut_cvd  = row.get("cvd_delta_1m")
                spot_cvd = row.get("spot_cvd_delta_1m")
                row["cvd_divergence"] = round(float(fut_cvd) - float(spot_cvd), 4) if (fut_cvd is not None and spot_cvd is not None) else None

            writer.writerow(row)
            written += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [ERR] {ts}: {e}")

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t_start
            rate = (i + 1) / elapsed
            remaining = (len(to_build) - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{len(to_build)}] {rate:.1f} rows/s | ETA: {remaining/60:.1f} min")

total_time = time.time() - t_start
print(f"\nDone: {written} rows written, {errors} errors | {total_time:.1f}s ({written/total_time:.1f} rows/s)")
