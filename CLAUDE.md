# CLAUDE.md — BTC Cascade Liquidation Predictor

> Tài liệu này là single source of truth cho Claude Code khi làm việc với project.
> Cập nhật lần cuối: 24/05/2026

---

## Mục đích dự án

Hệ thống dự đoán **cascade liquidation BTC Futures (Binance USDS-M)** để tìm cơ hội trade ngắn hạn.

**Ý tưởng cốt lõi:**
- Khi nhiều vị thế bị forced liquidation cùng lúc (cascade), giá BTC di chuyển mạnh theo 1 chiều trong vài phút
- Model dự đoán xác suất cascade xảy ra trong 1–3 phút tới → fire tín hiệu trade
- Dùng maker order để tránh taker fee (0.10%) — cascade median move chỉ ~0.029%

---

## Kiến trúc hệ thống — 5 tầng

```
Tầng 1  collector/main.py          7 Binance streams → data/raw CSVs
Tầng 2  feature_engine/run.py      Build features mỗi 1 phút → features_1m.csv
Tầng 3  feature_engine/label_builder.py   Build cascade + TP-hit labels
Tầng 4  ml/train.py + auto_train.py       Ensemble RF+LR+XGB, retrain mỗi 1h
Tầng 5  signal/run.py              Predict mỗi 10s → paper_trades.csv
```

### Services chạy (tmux session `btc`)

| Window | File | Chức năng | Interval |
|--------|------|-----------|----------|
| 0 | `signal/run.py` | Predict + fire paper trade | 10s |
| 1 | `collector/main.py` | 7 Binance WS/REST streams | real-time |
| 2 | `feature_engine/run.py` | Features + labels | 1 phút |
| 3 | `server/manage.py` | Dashboard Django | http://localhost:8000 |
| 4 | `ml/auto_train.py` | Auto retrain | 60 phút |
| 5 | `scripts/monitor_short.py` | Monitor | — |
| 6 | `scripts/signal_validator.py` | Validate signals (no cooldown) | 10s |

tmux session `sol`: SOL pipeline tương tự (4 windows), còn quá sớm.

---

## Config (single source of truth: `config.py`)

| Parameter | Giá trị | Ghi chú |
|-----------|---------|---------|
| `SIGNAL_THRESHOLD` | **0.65** | env var |
| `CASCADE_TP_PCT` | **0.120%** | env var |
| `CASCADE_SL_PCT` | **0.120%** | env var |
| `SIGNAL_COOLDOWN` | **900s (15 phút)** | per direction |
| `MAX_TTC` | **2.0 phút** | max time-to-cascade |
| `USE_MAKER` | **true** | maker order |
| `MAKER_OFFSET_PCT` | **0.005%** | offset entry |
| ~~`LIQ_FILTER_USD`~~ | ~~$500k~~ | **Đã xoá 23/05** — model tự học |

---

## Model

### Ensemble RF + LR + XGB (production)

- **6 cascade models**: `ens_cascade_{long/short}_{1/2/3}m.pkl`
- **6 TP-hit models**: `ens_tp_hit_{long/short}_{1/2/3}m.pkl` — chưa production (cần 50k+ rows)
- Artifact path: `ml/artifacts/`
- Meta: `ml/artifacts/meta.json`

### Hiệu quả model (24/05/2026 17:13 UTC, 15,331 rows)

| Target | AUC test |
|--------|----------|
| cascade_long_1m | **0.784** |
| cascade_long_2m | 0.665 |
| cascade_long_3m | 0.639 |
| cascade_short_1m | **0.747** |
| cascade_short_2m | 0.698 |
| cascade_short_3m | 0.654 |
| **Avg** | **0.698** |

- **188 lần auto-train** kể từ đầu (từ 2,437 → 15,331 rows)
- AUC lịch sử: min=0.49 / max=0.76 / avg=0.680
- AUC đang dần ổn định quanh **0.700** khi rows > 14k

### Labels

```
cascade_long_Xm  = 1 nếu sum(liq_short_usd[T→T+Xm]) > 3× baseline/min × X
cascade_short_Xm = 1 nếu sum(liq_long_usd[T→T+Xm])  > 3× baseline/min × X
```

Baseline tính bằng expanding lookback: 30m → 2h → 6h → 24h → global median.

Base rate: long ~7.8%, short ~8.9% (tại 3m horizon).

---

## Data

| File | Rows | Size | Ghi chú |
|------|------|------|---------|
| `features_1m.csv` | 15,329 | — | 09/05 → 24/05 (15.3 ngày) |
| `klines_1s.csv` | 1,220,726 | 101.8 MB | Dùng check outcome |
| `aggtrades.csv` | 1,815,480 | 135.2 MB | Futures CVD |
| `orderbook.csv` | 1,306,954 | 302.3 MB | Top 5 bid/ask |
| `liquidations.csv` | 417,114 | 29.4 MB | Event chính |
| `open_interest.csv` | 60,954 | 3.6 MB | |

38 features trong model (xem `feature_engine/build_features.py` và `FEATURE_COLS` trong `ml/train.py`). Gồm: price, volatility, CVD, orderbook imbalance, whale trades, OI, funding rate, liquidation stats.

**Market regime:** Sideways / downtrend — chưa thấy bull market hay high-vol regime.

---

## Hiệu quả thực tế

### Paper Trading (13/05 → 24/05, 141 trades)

| | n | WIN | LOSS | EXPIRED | Precision (W/L) | Total PnL |
|--|---|-----|------|---------|-----------------|-----------|
| **LONG** | 101 | 6 | 70 | 24+1 | **7.9%** (n=76) | **-25.35%** |
| **SHORT** | 40 | 4 | 3 | 30+3 | **57.1%** (n=7) | **+0.12%** |
| **Total** | 141 | 10 | 73 | 54+4 | 12.0% (n=83) | **-25.23%** |

> **LONG hoàn toàn không viable.** 66 LONG loss liên tiếp từ 15–18/05 (market downtrend mạnh).
> **SHORT có triển vọng** nhưng n=7 quá nhỏ để kết luận (CI rộng).
> **EXPIRED 38%** — TP/SL 0.12% quá chật, giá không di chuyển đủ trong 3 phút.

### Signal Validator (14/05 → 24/05, 53 signals, 5.3/ngày)

| | Signals | TP | FP | PENDING | Precision |
|--|---------|----|----|---------|-----------|
| SHORT | 29 | 12 | 16 | 1 | **42.9%** (n=28) |
| LONG | 24 | 10 | 13 | 1 | **43.5%** (n=23) |
| **Total** | **53** | **22** | **29** | **2** | **43.1%** |

Precision theo prob bucket:
- `[0.65, 0.70)`: 75% (n=9) — **vùng prob thấp lại precision cao nhất**
- `[0.70, 0.80)`: ~41% (n=12)
- `[0.80+)`: 100% (n=2, quá nhỏ)

> Validator không có cooldown → bắt nhiều hơn paper trader. 2 FP SHORT cách nhau 6 phút = 1 event thật (double-fire).

---

## Điều kiện live trade (chưa đạt)

| Điều kiện | Mục tiêu | Hiện tại |
|-----------|----------|---------|
| SHORT precision | ≥ 75% sustained | 57.1% (n=7 paper) / 42.9% (n=28 validator) |
| Resolved signals | ≥ 50 SHORT | n=7 paper / n=28 validator |
| Data | ≥ 30 ngày, nhiều regime | 15.3 ngày, sideways/downtrend only |
| **Kết luận** | | ❌ **Chưa đủ** |

---

## Khó khăn & Giới hạn

### Khó khăn kỹ thuật đã giải quyết

1. **Double write bug** (`label_builder.py`): `build_pending_labels()` ghi CSV 2 lần/phút — fix 23/05
2. **Recompute O(n) toàn bộ**: `build_tp_labels()` recompute 14k rows mỗi phút — fix thành incremental O(new_rows)
3. **Signal validator dùng RF thay vì ensemble**: validator chỉ gọi `models[0]` — fix thành `_ensemble_prob(RF+LR+XGB)`
4. **Timestamp parsing**: `pd.to_datetime()` trên mixed-format Series → luôn dùng `format="ISO8601"`
5. **Liq filter phản tác dụng**: `LIQ_FILTER_USD=$500k` là hard filter bên ngoài, trong khi `liq_total_1m` đã là feature #3 của model → xoá 23/05

### Giới hạn hiện tại

1. **~15 ngày data, 1 regime** (sideways/downtrend) — model chưa thấy bull market hay high-vol
2. **LONG không viable**: precision 7.9%, lỗ -25% trong 2 tuần — tuyệt đối không trade LONG
3. **SHORT n nhỏ**: paper_trades n=7 resolved, CI quá rộng → 57.1% không có nghĩa thống kê
4. **EXPIRED nhiều (38%)**: TP/SL 0.12% quá nhỏ so với volatility thực — giá thường không đủ move trong 3 phút
5. **Cascade BTC median 0.029% < taker fee 0.10%** → chỉ viable với maker orders
6. **TP-hit model chưa dùng**: positive rate 1.5–3.8%, cần 50k+ rows để học được
7. **SOL pipeline**: 3 trades, 3 LOSS — quá sớm, chưa đủ data
8. **DL models kém hơn Ensemble**: GJR-GARCH+GRU AUC=0.653 vs Ensemble 0.698 — cần 50k+ rows

### Pattern quan sát được

- Sau cascade lớn (liq spike), hay xuất hiện **dead cat bounce** → 3 LONG loss liên tiếp 22–23/05
- Validator precision ở prob [0.65, 0.70) = 75% **cao hơn** prob [0.70, 0.80) = 41% — likely overfitting vùng high-prob với data ít
- SHORT EXPIRED 75% (30/40) — cần xem xét nới TP hoặc tăng OUTCOME_WINDOW

---

## Việc cần làm

### Đang chạy tự động
- Tích lũy resolved SHORT trades: target n=50 (validator hiện 28/50)
- Auto retrain mỗi 60 phút

### Cần can thiệp khi đạt milestone
- **Khi validator SHORT n=50**: đánh giá lại precision, xem xét raise threshold lên 0.70
- **Khi paper_trades SHORT n=20**: đủ để kết luận sơ bộ về precision
- **Khi 30 ngày data**: xem xét mở rộng LONG nếu có bull regime

### Cải thiện dài hạn (cần 50k+ rows)
- Retrain TP-hit models với klines_1s (chính xác hơn close price 1m)
- Optuna hyperparameter tuning
- Walk-forward backtest trước khi scale vốn
- DL models (GJR-GARCH+GRU, Bi-LSTM) competitive với Ensemble
- Thêm Binance API execution (~50 dòng code)

---

## File structure quan trọng

```
config.py                       Single source of truth cho tất cả config
collector/
  main.py                       Entry point: 7 async streams
  ws_*.py / rest_*.py           Từng stream riêng
feature_engine/
  run.py                        Entry point: features + labels mỗi 1 phút
  build_features.py             build_feature_row() — 38 features
  label_builder.py              build_pending_labels(), build_tp_labels()
  feat_*.py                     Feature modules (price, liq, OI, funding...)
ml/
  train.py                      Train 6 cascade + 6 TP-hit models
  auto_train.py                 Auto retrain mỗi 1h, patience-based
  predict.py                    load_model(), predict_cascade_signal()
  artifacts/                    .pkl models + meta.json + train_history.json
signal/
  run.py                        Predict mỗi 10s, cooldown, paper log
  paper_log.py                  log_signal(), check_outcomes()
  notifier.py                   Telegram notification
scripts/
  signal_validator.py           Validate signals (no cooldown, full ensemble)
  monitor_short.py              Monitor SHORT performance
server/                         Django dashboard http://localhost:8000
data/
  features_1m.csv               Main dataset
  paper_trades.csv              Paper trading log
  signal_outcomes.csv           Validator log
  klines_1s.csv                 1-second candles (outcome check)
notebooks/
  model_selection.ipynb         Benchmark: RF/XGB/LGB/CatBoost + GRU/TDNN/BiLSTM
```

---

## Quy tắc khi làm việc với project

1. **Không trade LONG** — precision 7.9%, không viable với bất kỳ điều kiện nào hiện tại
2. **Không raise threshold quá 0.75** cho đến khi có n≥50 resolved signals
3. **Luôn dùng `format="ISO8601"`** trong `pd.to_datetime()` trên Series datetime
4. **Không thêm hard filter ngoài model** — model đã học các feature như `liq_total_1m`
5. **Kiểm tra `has_open_trade()` và cooldown** trước khi thêm logic signal mới
6. **Test incremental trước O(n)** — `build_tp_labels()` là ví dụ điển hình
7. **Không deploy DL models vào production** cho đến khi AUC > Ensemble + 0.01 sustained

---

## Git remotes

- **GitLab** (origin): `https://git.nsts.com.vn/hoanglongvbhp0703/hoanglongvbhp.git`
- **GitHub**: `https://github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor.git`

Push cả 2: `git push origin main && git push github main`
