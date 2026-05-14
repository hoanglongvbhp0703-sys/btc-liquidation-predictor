# BTC Cascade Liquidation Predictor

> Real-time ML system dự đoán BTC có xảy ra cascade liquidation trong 1/2/3 phút tới không.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![Model](https://img.shields.io/badge/model-RandomForest-orange.svg)](https://scikit-learn.org)
[![Django](https://img.shields.io/badge/backend-Django%20Channels-092E20.svg)](https://channels.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## Overview

Hệ thống stream dữ liệu thật từ Binance Futures, tính 46 features mỗi 1 phút, và chạy RandomForest classifier để dự đoán khả năng xảy ra cascade liquidation. Khi xác suất vượt ngưỡng, signal được ghi vào paper trades.

---

## Kết quả hiện tại

> **Dataset:** 5,335 rows labeled · 5 ngày thật từ Binance (09–14/05/2026)  
> **Model:** RandomForest `n_estimators=300, max_depth=10, class_weight=balanced`  
> **Retrain:** tự động mỗi 1h (`ml/auto_train.py`)  
> **Threshold:** 0.60 (configurable qua `.env`)

### AUC-ROC — out-of-sample (test set, 20% cuối theo thời gian)

| Direction | 1m | 2m | 3m |
|---|---|---|---|
| SHORT | **0.770** | 0.741 | 0.735 |
| LONG  | 0.668 | 0.634 | 0.627 |

> AUC > 0.70 trên SHORT là benchmark tốt cho tín hiệu ngắn hạn 1 phút.  
> AUC LONG ~0.65 — đủ để trade nhưng cần thêm dữ liệu để cải thiện.

### Precision / Recall — test set (1,067 rows, 05/13→05/14)

| Threshold | SHORT Prec | SHORT Recall | SHORT F1 | LONG Prec | LONG Recall | LONG F1 |
|---|---|---|---|---|---|---|
| 0.50 | 49.4% | 30.1% | 37.4% | 16.0% | 3.7% | 6.0% |
| 0.55 | 53.4% | 21.2% | 30.4% | 40.0% | 3.7% | 6.8% |
| **0.60** ← current | **56.8%** | **14.4%** | **23.0%** | **42.9%** | **2.8%** | **5.2%** |
| 0.65 | 60.0% | 12.3% | 20.5% | 66.7% | 1.9% | 3.6% |
| 0.70 | 62.5% | 6.8% | 12.3% | 100% | 0.9% | 1.8% |

> **Lưu ý:** Test set chỉ có 1,067 rows (~30h), số signal nhỏ (37 @ 0.60 cho SHORT).  
> Các chỉ số sẽ ổn định hơn khi tích lũy thêm 2–4 tuần data.

### So sánh: in-sample vs out-of-sample

| | SHORT in-sample | SHORT out-of-sample |
|---|---|---|
| Precision @ 0.60 | 93.1% | 56.8% |
| Recall @ 0.60 | 60.0% | 14.4% |

> Gap lớn giữa in-sample và out-of-sample = dấu hiệu overfitting nhẹ.  
> Nguyên nhân: chỉ 5 ngày data, một market regime (BTC sideways $79K).  
> Giải pháp: tích lũy data từ nhiều regime khác nhau (trending, high volatility).

### Paper Trading (đang chạy)

| Trades | WIN | LOSS | EXPIRED | Total PnL | Avg PnL/trade |
|---|---|---|---|---|---|
| 5 | 0 | 0 | 5 | +0.25% | +0.05% |

> Tất cả EXPIRED = giá không chạm TP (0.8%) cũng không chạm SL (0.5%) trong 3 phút.  
> TP/SL/window cần calibrate dựa trên thêm dữ liệu thực tế.  
> **Chưa đủ dữ liệu để đánh giá live performance** — cần tối thiểu 20–30 trades có outcome.

---

## Architecture

```
Binance Futures WebSocket / REST
            │
            ▼
┌───────────────────┐
│   collector/      │  Layer 1 — 8 async streams → data/*.csv
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  feature_engine/  │  Layer 2+3 — 46 features mỗi 1 phút
│  label_builder    │             + label cascade_short/long_Xm
└────────┬──────────┘
         │  data/features_1m.csv
         ▼
┌───────────────────┐
│      ml/          │  Layer 4 — RandomForest (n=300, balanced)
│  train.py         │            6 models: SHORT/LONG × 1/2/3m
│  auto_train.py    │            auto-retrain mỗi 1h
└────────┬──────────┘
         │  ml/artifacts/ens_cascade_*_*m.pkl
         ▼
┌───────────────────┐
│    signal/        │  Layer 5 — inference + paper trading
└────────┬──────────┘
         │  data/paper_trades.csv
         ▼
┌───────────────────┐
│    server/        │  Layer 6 — Django + Channels WebSocket dashboard
└───────────────────┘
```

---

## Project Structure

```
btc-liq-predictor/
├── collector/              # Layer 1 — Binance WebSocket collectors
│   ├── main.py             #   Entry point (asyncio multi-stream)
│   ├── ws_kline.py         #   klines_1s.csv
│   ├── ws_liquidation.py   #   liquidations.csv
│   ├── ws_orderbook.py     #   orderbook.csv
│   ├── ws_aggtrade.py      #   aggtrades.csv (futures CVD)
│   ├── ws_spot_aggtrade.py #   spot_aggtrades.csv (spot CVD)
│   ├── rest_oi.py          #   open_interest.csv
│   ├── rest_funding.py     #   funding_rate.csv
│   ├── rest_basis.py       #   basis.csv (futures-spot basis)
│   └── db.py               #   CSV append helper
│
├── feature_engine/         # Layer 2+3 — Features + labels
│   ├── run.py              #   Loop mỗi 1 phút
│   ├── build_features.py   #   Merge 46 features thành 1 row
│   ├── label_builder.py    #   cascade_short/long_Xm labels
│   ├── load_data.py        #   CSV readers
│   └── feat_*.py           #   Per-source feature modules (8 files)
│
├── ml/                     # Layer 4 — Training & inference
│   ├── train.py            #   RandomForest, 6 models, time-split
│   ├── auto_train.py       #   Auto-retrain mỗi 1h
│   ├── predict.py          #   load_model() / predict_signal()
│   └── artifacts/          #   ens_cascade_*.pkl + meta.json (gitignored)
│
├── signal/                 # Layer 5 — Signal generation
│   ├── run.py              #   Inference loop mỗi 1 phút
│   ├── paper_log.py        #   Log + evaluate paper trades
│   └── notifier.py         #   Telegram alerts (optional)
│
├── server/                 # Layer 6 — Web dashboard
│   ├── btc_dashboard/      #   Django project (settings, asgi, urls)
│   ├── dashboard/          #   App: views, consumers, broadcaster
│   ├── static/             #   JS (LightweightCharts, Chart.js)
│   └── templates/
│
├── scripts/
│   ├── monitor_short.py    #   Real-time SHORT signal monitor (tmux)
│   └── rebuild_features.py #   Rebuild features_1m.csv từ raw data
│
├── notebooks/
│   └── model_selection.ipynb   # Benchmark: RF vs LightGBM vs Ensemble
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── data/                   # gitignored — generated at runtime
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml  # 5 services: collector, feature_engine,
│                           #   auto_train, signal, dashboard
├── config.py               # Single source of truth: paths + constants
├── .env.example
├── Makefile
└── pyproject.toml
```

---

## Quick Start

```bash
# 1. Setup
git clone <repo-url> && cd btc-liq-predictor
make setup
cp .env.example .env   # set DJANGO_SECRET_KEY

# 2. Chạy từng service (terminal riêng)
make collector         # thu thập data Binance
make features          # build features mỗi 1 phút
make auto-train        # retrain model mỗi 1h
make signal            # inference + paper trades
make server            # dashboard http://localhost:8000

# Hoặc dùng tmux (xem cả 5 service cùng lúc)
make tmux

# Hoặc Docker (production)
make docker-up
```

---

## Giám sát signal SHORT real-time

```bash
make monitor           # mở monitor trong tmux window hiện tại
```

Output mỗi 60 giây: bảng TP/FP/FN + Precision/Recall/F1 + tự reload model khi auto_train xong.

---

## ML Model

**Algorithm:** RandomForest (`n_estimators=300, max_depth=10, class_weight=balanced`)

**Benchmark:** RF avg AUC 0.70 > LightGBM 0.67 > Ensemble(RF+LR+XGB) 0.66 trên real data.  
Xem: [`notebooks/model_selection.ipynb`](notebooks/model_selection.ipynb)

**46 features:**

| Category | Features |
|---|---|
| Price | price_change_1m/30s, volatility_1m, volume_1m, taker_buy_ratio |
| Liquidation | liq_long/short_usd_1m, liq_total, liq_ratio, liq_accel_30s |
| Order book | imbalance_now/avg_1m/trend, spread, bid/ask_vol, wall_ratio |
| CVD futures | cvd_delta_1m/30s, whale_buy/sell_count/net/usd, whale_dominance |
| CVD spot | spot_cvd_delta_1m/30s, cvd_divergence |
| Basis | basis_pct, basis_change_1m, basis_positive |
| Open interest | delta_oi_1m/30m/1h, oi_acceleration |
| Funding | funding_rate, funding_bias, long/short_heavy, trend_3h, urgency |

**Label:**
- `cascade_short_Xm = 1` nếu `min(low[T → T+Xm]) ≤ liq_zone_lower`
- `cascade_long_Xm  = 1` nếu `max(high[T → T+Xm]) ≥ liq_zone_upper`

---

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Default | Mô tả |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | — | Django secret key |
| `SIGNAL_THRESHOLD` | No | 0.60 | Ngưỡng probability để bắn signal |
| `MIN_RR` | No | 1.5 | Tỷ lệ R:R tối thiểu |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram alert |
| `TELEGRAM_CHAT_ID` | No | — | Telegram chat ID |

---

## Commands

```bash
make status        # xem trạng thái tất cả services
make train         # train model thủ công
make monitor       # giám sát SHORT signal real-time
make rebuild       # rebuild features_1m.csv từ raw data
make test          # chạy test suite
make lint          # flake8
make clean         # xóa cache
```

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml logs -f
```

5 services: `collector`, `feature_engine`, `auto_train`, `signal`, `dashboard`.

---

## Roadmap

- [ ] 2-3 tuần paper trading để xác nhận precision/recall trên live data
- [ ] Walk-forward backtesting (nhiều splits)
- [ ] Calibrate TP/SL/window cho paper trades (hiện tại: 0.8%/0.5%/3min)
- [ ] Live PnL thay thế paper trading
- [ ] Multi-symbol (ETH, SOL)
- [ ] Optuna hyperparameter tuning

---

## License

MIT
