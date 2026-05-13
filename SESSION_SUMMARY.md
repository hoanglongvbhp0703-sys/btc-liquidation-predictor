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
ml/train.py → Ensemble (RF + LR + XGBoost_GPU) × 6 targets
        ↓
signal/run.py → paper trading (prob ≥ 0.70 AND ttc ≤ 2m)
        ↓
server/ (Django + Channels) → dashboard http://localhost:8000
```

---

## Trạng thái hiện tại (2026-05-13)

### Services (tmux session `btc`)
| Window | Service | Status |
|---|---|---|
| `btc:collector` (7) | collector | ✅ running |
| `btc:features` (0) | feature engine | ✅ running |
| `btc:signal` (3) | signal / paper trading | ✅ running |
| `btc:autotrain` (1) | auto retrain mỗi 60 phút | ✅ running |
| `btc:server` (2) | Django + Daphne port 8000 | ✅ running |
| `btc:monitor` (4) | monitor | ✅ running |

### Data
| File | Rows | Range |
|---|---|---|
| `data/features_1m.csv` | ~4,343 | 2026-05-09 → 2026-05-13 UTC |

### Model — Ensemble (RF + LR + XGBoost_GPU)
AUC dưới đây từ `notebooks/model_selection.ipynb` (80/20 time split, no leakage):

| Target | Ens_RF+LR+XGB | RF | LR | XGB | LGBM (baseline) |
|---|---|---|---|---|---|
| cascade_long_1m  | 0.6127 | 0.6339 | 0.5793 | 0.6181 | 0.6037 |
| cascade_long_2m  | 0.5732 | 0.6037 | 0.5597 | 0.5876 | 0.5587 |
| cascade_long_3m  | 0.5759 | 0.5795 | 0.5612 | 0.5912 | 0.5603 |
| cascade_short_1m | **0.7660** | 0.7674 | 0.7556 | 0.7234 | 0.7080 |
| cascade_short_2m | **0.7694** | 0.7615 | 0.7581 | 0.7141 | 0.7202 |
| cascade_short_3m | **0.7553** | 0.7505 | 0.7475 | 0.6681 | 0.6938 |
| **avg** | **0.6754** | 0.6827 | 0.6602 | 0.6504 | 0.6408 |

- Short targets AUC ≥ 0.70 ✅ — long targets cần thêm data ❌
- Bootstrap CI: Ens vs LightGBM — short targets **significant** (p<0.05), long targets chưa đủ

### GPU
- **NVIDIA RTX 3090** (24GB) — XGBoost dùng GPU (`device='cuda'`, ~1s/target)
- LightGBM không có CUDA → loại khỏi ensemble (chỉ dùng làm baseline so sánh)

### GitHub
Repo: `https://github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor`

---

## Thay đổi trong session (2026-05-13 — cleanup)

### 1. Đổi model: LightGBM → Ensemble (RF + LR + XGBoost_GPU)
- `ml/train.py`: train 3 models/target, lưu `ens_cascade_{dir}_{h}m.pkl`
  - RF: `n_estimators=300, max_depth=10, class_weight='balanced'`
  - LR: `class_weight='balanced', max_iter=500`
  - XGB: `n_estimators=500, device='cuda', scale_pos_weight=spw`
- `ml/predict.py`: avg prob 3 models, fallback về `lgb_*.pkl` nếu tồn tại

### 2. broadcaster.py — cache predictions (mỗi phút, không phải mỗi giây)
- Thêm `_get_predictions(feat)`: chỉ recompute khi feature timestamp thay đổi
- Trước: 18 `predict_proba()` calls/giây → Sau: ~1 lần/phút

### 3. signal/run.py — fix references cũ
- Docstring + error message: `features_5m.csv` → `features_1m.csv`, `5 phút` → `1 phút`
- `MODEL_FILE`: `lgb_cascade_long_3m.pkl` → `ens_cascade_long_3m.pkl`

### 4. notebooks/ — dọn dẹp + viết lại
- Xóa: `compare_models.ipynb`, `compare_all_models.ipynb`, `compare_all_models_output.ipynb`, `.py` scripts, `catboost_info/`
- Giữ: `model_selection.ipynb` (442KB, output đầy đủ) + `compare_all_auc.png` + `roc_curves.png`
- Fixes trong notebook: data leakage, production hyperparams, ROC curves, Brier, bootstrap CI

### 5. Code cleanup & bug fixes (2026-05-13)
**Bugs thực sự:**
- `broadcaster.py`: `MODEL_FILE` trỏ `lgb_cascade_long_3m.pkl` → đổi thành `ens_cascade_long_3m.pkl` (reload model từng bị broken)
- `data_reader.py` `load_signal_state()`: key `cvd_delta_5m`/`delta_oi_5m` → `cvd_delta_1m`/`delta_oi_1m`
- `feature_engine/run.py` print: key `cvd_delta_5m`/`dist_to_upper` → `cvd_delta_1m`/`liq_total_1m`

**Dead code removed:**
- `ml/train.py`: xóa `_train_regressor()` (never called, `NO_CASCADE_VALUE` undefined), xóa import `LGBMRegressor/early_stopping/log_evaluation/mean_absolute_error`
- `ml/train.py`: đơn giản hóa `time_split()` → 2-way split (val set không được dùng trong classifier)
- `ml/auto_train.py`: xóa alias thừa `HISTORY_FILE`/`MIN_LABELED`, xóa double `import sys`

**Stale docstrings/strings fixed:**
- `feature_engine/run.py`: `5 phút`→`1 phút`, `features_5m.csv`→`features_1m.csv`
- `feature_engine/label_builder.py`: horizons `{5..30}`→`{1,2,3}`, `features_5m.csv`→`features_1m.csv`
- `ml/auto_train.py`: print `features_5m.csv`→`features_1m.csv`
- `ml/predict.py`: `model_info()` in `/6`→`/3`; xóa `ttc_long`/`ttc_short` khỏi ctx

---

## Kiến trúc & config quan trọng

```python
# config.py
FEATURES_FILE     = DATA_DIR / "features_1m.csv"
HORIZONS          = [1, 2, 3]
SIGNAL_THRESHOLD  = 0.70
MIN_RR            = 1.5
MIN_ROWS_TRAIN    = 200
RUN_INTERVAL_FE   = 60  # seconds

# label_builder.py
LOOKBACK_MINUTES  = 30
MIN_LIQ_THRESHOLD = 10_000  # $10k/min
# cascade = 1 nếu sum(liq[T→T+Xm]) > 3 × avg_per_min × X

# predict.py (ensemble)
CASCADE_TP_PCT = 0.008   # +0.8%
CASCADE_SL_PCT = 0.005   # -0.5%
max_ttc        = 2.0     # minutes
# Ensemble: avg(RF_prob, LR_prob, XGB_prob) >= 0.70

# paper_log.py
OUTCOME_WINDOW = timedelta(minutes=3)
```

---

## 38 Features (ml/artifacts/meta.json)

```
price_change_1m, price_change_30s, volatility_1m, volume_1m, taker_buy_ratio,
liq_long_usd_1m, liq_short_usd_1m, liq_total_1m, liq_ratio_1m, liq_accel_30s,
imbalance_now, imbalance_avg_1m, imbalance_trend, spread_now, bid_vol_now,
ask_vol_now, wall_ratio,
cvd_delta_1m, cvd_delta_30s,
whale_buy_count, whale_sell_count, whale_net, whale_buy_usd_1m, whale_sell_usd_1m, whale_dominance,
delta_oi_1m, delta_oi_30m, delta_oi_1h, oi_acceleration,
funding_rate, funding_rate_abs, funding_bias, funding_long_heavy, funding_short_heavy,
funding_rate_change, funding_trend_3h, secs_to_next_funding, funding_urgency
```

---

## Cascade label definition

```
LOOKBACK = 30 phút lịch sử để tính baseline per-minute
threshold = max(avg_liq_per_min × 3, $10k/min)

cascade_long_Xm  = 1 nếu sum(liq_short_usd[T→T+Xm]) > 3 × avg_short_pm × X
cascade_short_Xm = 1 nếu sum(liq_long_usd[T→T+Xm])  > 3 × avg_long_pm  × X

liq_short_usd = usd_value where side == 'BUY'   (SHORT bị liq → giá TĂNG)
liq_long_usd  = usd_value where side == 'SELL'  (LONG bị liq  → giá GIẢM)
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

## Việc cần làm tiếp theo

### Mục tiêu validation
| Condition | Status |
|---|---|
| AUC short ≥ 0.70 | ✅ đạt (0.74–0.77) |
| AUC long ≥ 0.65 | ❌ chưa (0.57–0.61) |
| Precision@0.70 ≥ 50% | ❌ cần kiểm tra sau 50+ signals |
| Paper trading win rate ≥ 55% sau 50 trades | ❌ chưa đủ trades |

### Khi có đủ paper trades (≥ 50)
- Walk-forward backtest thủ công
- Xác minh precision@0.7 ≥ 50%
- Nếu pass → live vốn nhỏ (5-10% tổng vốn, đòn bẩy 3-5x)

### Roadmap dài hạn
- [ ] Optuna hyperparameter tuning cho ensemble
- [ ] Walk-forward backtesting module
- [ ] Live PnL thay paper trading
- [ ] Multi-symbol (ETH, SOL)

---

## Lệnh khởi động lại nếu service chết

```bash
# Kiểm tra
tmux list-windows -t btc
tmux capture-pane -t btc:features -p | tail -5

# Restart từng service
tmux send-keys -t btc:features  ".venv/bin/python feature_engine/run.py" ENTER
tmux send-keys -t btc:signal    ".venv/bin/python signal/run.py" ENTER
tmux send-keys -t btc:autotrain ".venv/bin/python ml/auto_train.py" ENTER

# Server (phải chạy từ server/)
cd /home/coder/server && /home/coder/.venv/bin/daphne -b 0.0.0.0 -p 8000 btc_dashboard.asgi:application

# Train thủ công (ensemble)
cd /home/coder && .venv/bin/python ml/train.py

# Fill labels thủ công
.venv/bin/python feature_engine/label_builder.py
```

---

## File structure quan trọng

```
config.py                          ← central config (HORIZONS, FEATURES_FILE, etc.)
collector/main.py                  ← 6 async streams → data/raw/*.csv
feature_engine/
  run.py                           ← scheduler 60s, floor("1min")
  build_features.py                ← 38 features → features_1m.csv
  label_builder.py                 ← cascade labels 1/2/3m
ml/
  train.py                         ← Ensemble (RF + LR + XGBoost_GPU) × 6 targets
  predict.py                       ← load_model(), predict_cascade_*(), avg ensemble prob
  auto_train.py                    ← retrain mỗi 60 phút
  artifacts/                       ← ens_cascade_*.pkl, meta.json (gitignored)
signal/
  run.py                           ← inference 60s, paper trade entry
  paper_log.py                     ← ghi + check outcome WIN/LOSS/EXPIRED
server/
  dashboard/broadcaster.py         ← push WS tick 1s, predict cache per feat timestamp
  dashboard/data_reader.py         ← đọc CSV → dict
  static/js/signal.js              ← prob bar, curve chart, countdown 3m
data/
  raw/klines_1s.csv                ← price data 1s
  raw/liquidations.csv             ← liquidation events
  features_1m.csv                  ← 38 features + cascade labels
notebooks/
  model_selection.ipynb            ← model comparison duy nhất (442KB, output đầy đủ)
  compare_all_auc.png              ← AUC bar chart
  roc_curves.png                   ← ROC curves 6 targets
.vscode/settings.json              ← port 8000 label "BTC Dashboard"
```
