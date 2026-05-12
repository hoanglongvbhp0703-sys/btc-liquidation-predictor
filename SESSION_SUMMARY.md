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

## Trạng thái hiện tại (2026-05-12)

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
| `data/features_1m.csv` | ~2,676 | 2026-05-09 10:14 → 2026-05-12 12:36 UTC |

### Labels (tính đến 2026-05-12 ~12:36 UTC)
| Label | Labeled | Positives | Base rate |
|---|---|---|---|
| cascade_long_1m | 2,674 | 180 | 6.7% |
| cascade_long_2m | 2,674 | 192 | 7.2% |
| cascade_long_3m | 2,674 | 191 | 7.1% |
| cascade_short_1m | 2,674 | 199 | 7.4% |
| cascade_short_2m | 2,674 | 226 | 8.5% |
| cascade_short_3m | 2,674 | 221 | 8.3% |

### Model (lần train gần nhất: 2026-05-12 11:44 UTC)
| Model | AUC test |
|---|---|
| long_1m | 0.50 |
| long_2m | 0.50 |
| long_3m | 0.61 |
| short_1m | 0.64 |
| short_2m | 0.61 |
| short_3m | 0.59 |
| **avg** | **0.5749** |

AUC ~0.57 — còn thấp, cần ~10,000 rows để meaningful. Auto-train mỗi 60 phút sẽ tự cải thiện.

### GitHub
Repo: `https://github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor`
Commit mới nhất: `6986696d — refactor: migrate pipeline 5m→1m, horizons [1,2,3]m`

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

# predict.py
CASCADE_TP_PCT = 0.008   # +0.8%
CASCADE_SL_PCT = 0.005   # -0.5%
max_ttc        = 2.0     # minutes

# signal/run.py
MODEL_FILE   = ml/artifacts/lgb_cascade_long_3m.pkl
RUN_INTERVAL = 60

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

## Migration quan trọng đã thực hiện: 5m → 1m

| Hạng mục | Trước | Sau |
|---|---|---|
| Feature granularity | 5 phút | **1 phút** |
| Prediction horizons | [5,10,15,20,25,30]m | **[1, 2, 3]m** |
| Features file | features_5m.csv | **features_1m.csv** |
| TP / SL | +1.5% / -1.0% | **+0.8% / -0.5%** |
| max_ttc | 15m | **2m** |
| OUTCOME_WINDOW | 30m | **3m** |
| Models | 12 classifier + 2 regressor | **6 classifier** |
| Rows/day | ~288 | **~1,440** |

**Lý do:** cascade thật xảy ra trong vài giây → 2 phút. 5m quá chậm.

---

## Bugs đã fix (tất cả sessions)

1. `auto_train check_stable()`: logic sai → removed hard-stop, `history["stable"] = False` at startup
2. Feature engine: kill duplicate process
3. Server `urls.py`: remove `test_page` route → AttributeError
4. Signal: kill old process
5. `paper_log.py check_outcomes()`: fix SHORT direction
6. `paper_log.py`: thêm `close` column cho EXPIRED pnl
7. Feature engine: restart để load code mới (Python import cache)
8. Label threshold: sai per-hour → fix thành per-minute
9. Label print bug: `str.match(r"^[01]$")` fail trên float64 → `pd.to_numeric().isin([0,1])`
10. Dashboard table header: `TP (+1.5%)` → `TP (+0.8%)`, `SL (-1.0%)` → `SL (-0.5%)`

---

## Việc cần làm tiếp theo

### Ngắn hạn — pipeline tự chạy, không cần can thiệp
- Collector tích lũy ~1,440 rows/ngày
- Auto-train retrain mỗi 60 phút với data mới
- AUC sẽ cải thiện dần khi data tăng

### Mục tiêu data
| Rows | Dự kiến đạt | Kỳ vọng AUC |
|---|---|---|
| ~2,676 (hiện tại) | — | 0.57 |
| ~10,000 | +5 ngày | 0.65+ |
| ~20,000 | +12 ngày | 0.70+ |

### Khi AUC ≥ 0.65
- Walk-forward backtest thủ công
- Xác minh precision@0.7 ≥ 60%
- Check paper trading win rate ≥ 55% sau 50 trades

### Roadmap dài hạn
- [ ] Optuna hyperparameter tuning
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

# Nếu btc:signal chưa tồn tại
tmux new-window -t btc -n signal
tmux send-keys -t btc:signal ".venv/bin/python signal/run.py" ENTER

# Train thủ công
.venv/bin/python ml/train.py

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
  train.py                         ← 6 LGBMClassifier
  predict.py                       ← load_model(), predict_cascade_*()
  auto_train.py                    ← retrain mỗi 60 phút
  artifacts/                       ← lgb_cascade_*.pkl, meta.json (gitignored)
signal/
  run.py                           ← inference 60s, paper trade entry
  paper_log.py                     ← ghi + check outcome WIN/LOSS/EXPIRED
server/
  dashboard/broadcaster.py         ← push WS tick mỗi 1s
  dashboard/data_reader.py         ← đọc CSV → dict
  static/js/signal.js              ← prob bar, curve chart, countdown 3m
data/
  raw/klines_1s.csv                ← price data 1s
  raw/liquidations.csv             ← liquidation events
  processed/features_1m.csv        ← 38 features + cascade labels
```
