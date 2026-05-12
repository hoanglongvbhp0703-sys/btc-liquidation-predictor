# BTC Cascade Liquidation Predictor — Session Summary

## Hệ thống là gì

Real-time ML pipeline dự đoán BTC có xảy ra **cascade liquidation** trong N phút tới không.

```
Binance WebSocket/REST
        ↓
collector/ → data/raw CSV (klines, liq, orderbook, aggtrade, OI, funding)
        ↓
feature_engine/ → 38 features mỗi 1 PHÚT → features_1m.csv
        ↓
label_builder → cascade_long/short_1m/2m/3m
        ↓
ml/train.py → 6 LGBMClassifier (LONG+SHORT × 3 horizons)
        ↓
signal/run.py → paper trading (prob ≥ 0.70 AND ttc ≤ 2m)
        ↓
server/ (Django + Channels) → dashboard http://localhost:8000
```

---

## Migration quan trọng nhất session này: 5m → 1m

| Hạng mục | Trước | Sau |
|---|---|---|
| Feature granularity | 5 phút | **1 phút** |
| Prediction horizons | [5,10,15,20,25,30]m | **[1, 2, 3]m** |
| Label | cascade_long_30m | **cascade_long_3m** |
| Features file | features_5m.csv | **features_1m.csv** |
| TP / SL | +1.5% / -1.0% | **+0.8% / -0.5%** |
| max_ttc | 15m | **2m** |
| OUTCOME_WINDOW | 30m | **3m** |
| Models | 12 classifier + 2 regressor | **6 classifier (Model B bỏ)** |
| Rows/day | ~288 | **~1,440** |

**Lý do migrate:** cascade thật xảy ra trong vài giây → 2 phút. 5m quá chậm, signal tới khi cascade đã xong.

**Data analysis:**
- 3,077 phút data → CASCADE_LONG spikes (3× avg): 4.1%
- Predict +2m: 210 LONG pos, 179 SHORT pos — đủ để train
- Predict +3m: 280 LONG pos, 242 SHORT pos

---

## Trạng thái hiện tại

| Service | Tmux | Status |
|---|---|---|
| collector | `btc:collector` | ✅ running |
| features | `btc:features` | ⛔ stopped — cần restart |
| signal | `btc:signal` (window 3) | ⛔ stopped — cần restart |
| server | `btc:server` | ✅ running port 8000 |
| autotrain | `btc:autotrain` | ⛔ stopped — cần restart |
| monitor | `btc:monitor` | running |

**Backfill đang chạy (background):** ~2,378/~2,900 rows vào `features_1m.csv`

---

## Việc cần làm ngay khi vào chat mới

### 1. Chờ backfill xong rồi fill labels
```bash
# Kiểm tra backfill xong chưa
wc -l data/features_1m.csv   # target ~2,900 rows

# Fill cascade labels (1-3m) cho toàn bộ historical data
.venv/bin/python feature_engine/label_builder.py
```

### 2. Train model lần đầu
```bash
.venv/bin/python ml/train.py
```

### 3. Restart các services
```bash
# features (1m interval)
tmux send-keys -t btc:features ".venv/bin/python feature_engine/run.py" ENTER

# signal
tmux send-keys -t btc:signal ".venv/bin/python signal/run.py" ENTER

# autotrain
tmux send-keys -t btc:autotrain ".venv/bin/python ml/auto_train.py" ENTER
```

---

## File changes trong session này

### Đã thay đổi
| File | Thay đổi |
|---|---|
| `config.py` | HORIZONS=[1,2,3], FEATURES_FILE=features_1m.csv, RUN_INTERVAL_FE=60 |
| `feature_engine/feat_price.py` | price_change_1m/30s, volatility_1m, volume_1m |
| `feature_engine/feat_liquidation.py` | 5m→1m, thêm liq_accel_30s, **bỏ zone features** |
| `feature_engine/feat_aggtrade.py` | cvd_delta_5m→1m, cvd_delta_1m→30s, whale 5m→1m |
| `feature_engine/feat_oi.py` | delta_oi_5m→1m |
| `feature_engine/build_features.py` | window 1m, FEATURE_COLUMNS mới (38 cols) |
| `feature_engine/label_builder.py` | HORIZONS=[1,2,3], LOOKBACK=30m |
| `feature_engine/run.py` | interval 60s, floor("1min") |
| `ml/train.py` | FEATURE_COLS mới, bỏ Model B, 6 models |
| `ml/predict.py` | HORIZONS=[1,2,3], TP=0.8%, SL=0.5%, max_ttc=2m, bỏ ttc regressor |
| `ml/auto_train.py` | cascade_long_3m |
| `signal/run.py` | interval 60s, max_ttc=2m, MODEL_FILE=lgb_cascade_long_3m.pkl |
| `signal/paper_log.py` | OUTCOME_WINDOW=3m |
| `server/dashboard/broadcaster.py` | cvd_1m, delta_oi_1m, MODEL_FILE=lgb_cascade_long_3m.pkl |
| `server/static/js/signal.js` | CURVE_LABELS=[+1m,+2m,+3m], countdown 3m, TP/SL labels |
| `server/templates/dashboard/index.html` | OI Δ1m, CVD 1m, curve x-labels +1m/+2m/+3m |

### Đã xóa (dọn dẹp)
- `collector/crawl_coinank.py`, `crawl_liq_heatmap.py`
- `feature_engine/debug_check.py`
- `notebooks/` (benchmark cũ)
- `pipeline.txt`, `SESSION_SUMMARY.md` cũ
- `scripts/generate_fake_data.py`
- `server/db.sqlite3`
- `data/liq_heatmap.csv`, `data/liq_heatmap.json`
- `data/features_5m.csv` (replaced bởi features_1m.csv)
- `ml/artifacts/lgb_cascade_*.pkl` (schema cũ, cần retrain)

---

## Model artifacts (ml/artifacts/)

**Sau khi train xong, sẽ có:**
```
lgb_cascade_long_1m.pkl   imputer_cascade_long_1m.pkl
lgb_cascade_long_2m.pkl   imputer_cascade_long_2m.pkl
lgb_cascade_long_3m.pkl   imputer_cascade_long_3m.pkl   ← main model
lgb_cascade_short_1m.pkl  ...
lgb_cascade_short_3m.pkl  ← main model
meta.json
train_history.json
```

**Artifact cũ còn sót (không ảnh hưởng):** `imputer_long_*.pkl`, `lgb_model_long/short.pkl` — có thể xóa sau.

---

## Cascade label definition (không đổi)

```python
LOOKBACK = 30 phút (thay vì 2h trước — scale down cho 1m)
threshold = max(avg_liq_per_min × 3, $10k/min)

cascade_long_Xm  = 1 if sum(liq_short_usd[T→T+Xm]) > 2 × avg_short_per_min × Xm
cascade_short_Xm = 1 if sum(liq_long_usd[T→T+Xm])  > 2 × avg_long_per_min  × Xm
```

---

## Signal condition

```python
prob >= 0.70  AND  time_to_cascade <= 2m
TP = entry × 1.008  (+0.8%)
SL = entry × 0.995  (-0.5%)
R:R = 1.6
```

---

## Config quan trọng

```python
# config.py
HORIZONS         = [1, 2, 3]
SIGNAL_THRESHOLD = 0.70
MIN_RR           = 1.5
MIN_ROWS_TRAIN   = 200
RUN_INTERVAL_FE  = 60  # seconds

# predict.py
CASCADE_TP_PCT = 0.008
CASCADE_SL_PCT = 0.005
max_ttc        = 2.0
```

---

## Validation plan

1. **Walk-forward AUC** ≥ 0.65 (temporal split)
2. **Paper trading 2 tuần**: WIN rate ≥ 55% sau 50 trades
3. **Precision@0.7** ≥ 60%

---

## Bugs đã fix (tổng hợp tất cả sessions)

1. `auto_train check_stable()`: `0 <= (latest - best_prev) < 0.001`
2. Feature engine: kill duplicate process
3. Server: kill duplicate process, remove `test_page` từ urls.py
4. Signal: kill old process
5. `paper_log.py check_outcomes()`: fix SHORT direction
6. `paper_log.py`: thêm `close` column cho EXPIRED pnl
7. Feature engine: label_builder cũ được cache → cần restart để load code mới
8. `auto_train.py`: bỏ hard-stop khi "stable", tiếp tục train với data mới
9. **Migration 5m→1m**: toàn bộ pipeline đã update (session này)
