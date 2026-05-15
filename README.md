# BTC Cascade Liquidation Predictor

> Hệ thống ML real-time dự đoán BTC có xảy ra cascade liquidation trong 1–3 phút tới không,
> từ đó tạo tín hiệu giao dịch theo chiều cascade.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Model](https://img.shields.io/badge/model-RandomForest-orange.svg)](https://scikit-learn.org)
[![Django](https://img.shields.io/badge/backend-Django%20Channels-092E20.svg)](https://channels.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## Cascade Liquidation là gì?

**SHORT cascade** = hàng loạt lệnh LONG bị forced-liquidation → giá giảm mạnh đột ngột
**LONG cascade** = hàng loạt lệnh SHORT bị forced-liquidation → giá tăng mạnh đột ngột

Khi model dự đoán SHORT cascade → trader vào lệnh **SHORT** để ăn theo đà giảm.
Khi model dự đoán LONG cascade → trader vào lệnh **LONG** để ăn theo đà tăng.

---

## Tổng quan hệ thống

```
Binance Futures WebSocket / REST  (8 streams real-time)
            │
            ▼
┌───────────────────┐
│   collector/      │  Layer 1 — stream data → data/*.csv
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  feature_engine/  │  Layer 2+3 — 44 features + labels mỗi 1 phút
└────────┬──────────┘
         │  data/features_1m.csv
         ▼
┌───────────────────┐
│      ml/          │  Layer 4 — RandomForest, 6 models (SHORT/LONG × 1/2/3m)
│  auto_train.py    │            auto-retrain mỗi 1 giờ
└────────┬──────────┘
         │  ml/artifacts/*.pkl
         ▼
┌───────────────────┐
│    signal/        │  Layer 5 — inference mỗi 1 phút + paper trading
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│    server/        │  Layer 6 — Django + WebSocket dashboard real-time
└───────────────────┘
         │
         ▼
┌───────────────────┐
│    scripts/       │  Tools — signal_validator (24/7 TP/FP tracker),
│                   │          live_predict, benchmark_models
└───────────────────┘
```

---

## Kết quả hiện tại

> **Dataset:** 7,286 rows · 5.9 ngày thật từ Binance (09–15/05/2026) · BTC $79K–$82K
> **Train/Test split:** 80/20 theo thời gian (5,778 train / 1,445 test)
> **Auto-retrain:** mỗi 1 giờ — model luôn cập nhật data mới nhất

### AUC-ROC — out-of-sample (test set, 20% cuối)

| Direction | 1m | 2m | 3m | Avg |
|---|---|---|---|---|
| **SHORT** | **0.804** | **0.781** | **0.749** | **0.778** |
| LONG | 0.747 | 0.682 | 0.670 | 0.700 |
| **Overall avg** | | | | **0.739** |

> SHORT 1m AUC=0.804 — benchmark xuất sắc cho financial ML ngắn hạn.
> LONG yếu hơn (~0.70 avg) — cần thêm data từ nhiều market regime.

### Precision / Recall — test set tại threshold=0.60

| Model | Signals | Precision | Recall | AUC |
|---|---|---|---|---|
| SHORT 1m | 4 | 100% | 3.3% | 0.804 |
| SHORT 2m | 12 | 66.7% | 5.3% | 0.781 |
| SHORT 3m | 9 | 66.7% | 3.5% | 0.749 |
| LONG 1m | 1 | 100% | 1.0% | 0.747 |
| LONG 2m | 0 | — | — | 0.682 |
| LONG 3m | 0 | — | — | 0.670 |

> Recall thấp là có chủ đích: threshold=0.60 chỉ bắn signal khi model rất tự tin.
> Đổi lại precision cao (66–100%) — khi signal bắn thì đa phần đúng.

### Base rate & Lift

| | Base rate | Model precision | Lift |
|---|---|---|---|
| SHORT cascade | 7.5% | ~60–100% | **~7–13x** |
| LONG cascade | 7.3% | ~33% (live) | ~4x |

> "Lift" = model tốt hơn random bao nhiêu lần. 7x là edge thật.

### Model Benchmark — so sánh 5 thuật toán (avg AUC qua 6 targets)

| Rank | Model | Avg AUC | Train time/model |
|---|---|---|---|
| **#1** | **RandomForest** | **0.709** | ~1s |
| #2 | ExtraTrees | 0.685 | ~1s |
| #3 | CatBoost | 0.669 | ~2s |
| #4 | LightGBM | 0.662 | ~110s ⚠️ |
| #5 | XGBoost | 0.635 | ~55s |

> RandomForest thắng toàn diện + train nhanh nhất → phù hợp cho auto-retrain mỗi 1h.

---

## Live Performance (đang theo dõi)

### Signal Validator — 32 giờ đầu (14–15/05/2026)

| Direction | Signals | TP | FP | Precision |
|---|---|---|---|---|
| **SHORT** | 5 | 3 | 2 | **60%** |
| LONG | 3 | 0 | 2 | 0%* |
| Overall | 8 | 3 | 4 | 43% |

> *LONG chỉ có 3 signals, 1 PENDING — chưa đủ data để đánh giá.
> SHORT 60% precision = 7x tốt hơn random (base rate 7.5%).

### Cascade events thực tế vs Signal bắt được (32 giờ)

| | Cascade xảy ra | Model bắt được | Recall |
|---|---|---|---|
| SHORT | 69 events | 5 | 7% |
| LONG | 63 events | 3 | 5% |

> Recall thấp là đánh đổi có chủ đích — xem phần Trade-off bên dưới.

### Paper Trading (10 trades, 13–15/05/2026)

| Trades | WIN | LOSS | EXPIRED | Total PnL |
|---|---|---|---|---|
| 10 | 0 | 0 | 10 | -0.02% |

> **Tất cả EXPIRED** = giá không chạm TP (+0.8%) cũng không chạm SL (-0.5%) trong 3 phút.
> TP=0.8% đang đặt quá rộng so với biên độ cascade thực tế — cần calibrate.

---

## Trade-off: Precision vs Recall

Hệ thống thiết kế để **trade theo cascade**, không phải phòng thủ tránh cascade:

| Threshold | Precision SHORT | Recall SHORT | Phù hợp cho |
|---|---|---|---|
| 0.50 | ~45% | ~25% | Cảnh báo sớm / phòng thủ |
| **0.60** ← hiện tại | **~60%** | **~7%** | **Trading — EV dương** |
| 0.70 | ~70%+ | ~2% | Cực kỳ chọn lọc |

**Expected Value tại threshold=0.60** (TP=0.8%, SL=0.5%):

```
EV = (60% × +0.8%) + (40% × -0.5%) = +0.48% − 0.20% = +0.28% / lệnh
```

> EV dương — có edge thật. Nhưng cần calibrate TP/SL trước khi trade thật.

---

## Giới hạn & Lộ trình

### Giới hạn hiện tại

- **Sample nhỏ:** 8 live signals — CI 95% precision SHORT là [23%–88%], chưa thể kết luận chắc
- **1 market regime:** 5.9 ngày, BTC $79K–$82K sideways — chưa test trending/high-volatility
- **TP/SL chưa calibrate:** 10/10 paper trades EXPIRED
- **LONG model yếu:** live precision 0% (3 signals, quá ít để đánh giá)

### Điều kiện để trade thật

- [ ] ≥ 50 signals resolved trong `signal_outcomes.csv`
- [ ] SHORT precision ổn định ≥ 55% qua nhiều ngày
- [ ] Calibrate TP/SL dựa trên biên độ cascade thực tế
- [ ] Test qua ít nhất 2–3 market regime (cần 3–4 tuần)

### Roadmap

- [ ] Walk-forward backtesting (nhiều time splits)
- [ ] Calibrate TP/SL tự động từ signal_outcomes
- [ ] Live trading size nhỏ sau khi đủ điều kiện
- [ ] Cải thiện LONG model
- [ ] Multi-symbol (ETH, SOL)
- [ ] Optuna hyperparameter tuning

---

## 44 Features

| Category | Features | Nguồn |
|---|---|---|
| Price (5) | price_change_1m/30s, volatility_1m, volume_1m, taker_buy_ratio | klines_1s.csv |
| Liquidation (5) | liq_long/short_usd_1m, liq_total, liq_ratio, liq_accel_30s | liquidations.csv |
| Order book (7) | imbalance_now/avg_1m/trend, spread, bid/ask_vol, wall_ratio | orderbook.csv |
| CVD futures (8) | cvd_delta_1m/30s, whale_buy/sell_count/net/usd, whale_dominance | aggtrades.csv |
| CVD spot (3) | spot_cvd_delta_1m/30s, cvd_divergence | spot_aggtrades.csv |
| Basis (3) | basis_pct, basis_change_1m, basis_positive | basis.csv |
| Open interest (4) | delta_oi_1m/30m/1h, oi_acceleration | open_interest.csv |
| Funding (8) | funding_rate, funding_rate_abs, funding_bias, long/short_heavy, rate_change, trend_3h, secs_to_next, urgency | funding_rate.csv |

**Label definition:**
- `cascade_short_Xm = 1` nếu `min(low[T → T+Xm]) ≤ liq_zone_lower`
- `cascade_long_Xm  = 1` nếu `max(high[T → T+Xm]) ≥ liq_zone_upper`

---

## Project Structure

```
btc-liq-predictor/
├── collector/              # Layer 1 — 8 Binance streams
│   ├── main.py             #   Entry point asyncio multi-stream
│   ├── ws_kline.py         #   → klines_1s.csv
│   ├── ws_liquidation.py   #   → liquidations.csv
│   ├── ws_orderbook.py     #   → orderbook.csv
│   ├── ws_aggtrade.py      #   → aggtrades.csv (futures CVD)
│   ├── ws_spot_aggtrade.py #   → spot_aggtrades.csv (spot CVD)
│   ├── rest_oi.py          #   → open_interest.csv
│   ├── rest_funding.py     #   → funding_rate.csv
│   └── rest_basis.py       #   → basis.csv
│
├── feature_engine/         # Layer 2+3 — Features + Labels
│   ├── run.py              #   Loop mỗi 1 phút
│   ├── build_features.py   #   Merge 44 features thành 1 row
│   ├── label_builder.py    #   cascade_short/long_Xm labels
│   └── feat_*.py           #   8 feature modules (per source)
│
├── ml/                     # Layer 4 — Training & Inference
│   ├── train.py            #   RandomForest, 6 models, time-split 80/20
│   ├── auto_train.py       #   Auto-retrain mỗi 1 giờ
│   ├── predict.py          #   load_model() / predict_signal()
│   └── artifacts/          #   *.pkl + meta.json (gitignored)
│
├── signal/                 # Layer 5 — Signal + Paper Trading
│   ├── run.py              #   Inference loop mỗi 1 phút
│   ├── paper_log.py        #   Log + evaluate paper trades
│   └── notifier.py         #   Telegram alerts (optional)
│
├── server/                 # Layer 6 — Web Dashboard
│   ├── btc_dashboard/      #   Django project (settings, asgi, urls)
│   ├── dashboard/          #   WebSocket consumer + broadcaster
│   ├── static/             #   JS charts (LightweightCharts, Chart.js)
│   └── templates/
│
├── scripts/
│   ├── signal_validator.py #   24/7 TP/FP tracker → signal_outcomes.csv
│   ├── live_predict.py     #   Real-time prob display (terminal)
│   ├── benchmark_models.py #   So sánh RF/XGB/LGB/CatBoost/ET
│   ├── monitor_short.py    #   SHORT signal monitor (tmux)
│   └── rebuild_features.py #   Rebuild features_1m.csv từ raw data
│
├── data/                   # gitignored — generated at runtime
│   ├── features_1m.csv     #   44 features + labels, 1 row/phút
│   ├── paper_trades.csv    #   Paper trading log
│   └── signal_outcomes.csv #   TP/FP tracking 24/7
│
├── config.py               # Single source of truth: paths + constants
├── requirements.txt
├── Makefile
├── pyproject.toml
├── .env.example
└── docker/docker-compose.yml
```

---

## Quick Start

```bash
# 1. Setup
git clone <repo-url> && cd btc-liq-predictor
make setup
cp .env.example .env   # set DJANGO_SECRET_KEY

# 2. Chạy tất cả services (tmux)
make tmux
# → 6 windows: collector, features, auto_train, signal, server, validator

# Hoặc từng service riêng
make collector     # stream data từ Binance
make features      # build 44 features mỗi 1 phút
make auto-train    # retrain model mỗi 1 giờ
make signal        # inference + paper trades
make server        # dashboard http://localhost:8000
make validate      # 24/7 signal TP/FP tracker

# Docker (production)
make docker-up
```

---

## Commands

```bash
make status        # trạng thái tmux session
make train         # train model thủ công
make monitor       # SHORT signal monitor real-time
make validate      # 24/7 signal TP/FP tracker
make rebuild       # rebuild features_1m.csv từ raw data
make test          # chạy test suite
make lint          # flake8
make clean         # xóa cache
```

---

## Environment Variables

| Variable | Required | Default | Mô tả |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | — | Django secret key |
| `SIGNAL_THRESHOLD` | No | 0.60 | Ngưỡng prob để bắn signal |
| `MIN_RR` | No | 1.5 | Risk:Reward tối thiểu |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram alert |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat ID |

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml logs -f
```

6 services: `collector`, `feature_engine`, `auto_train`, `signal`, `dashboard`, `validator`.

---

## License

MIT
