# BTC Liquidation Predictor

> Real-time machine learning system that predicts whether Bitcoin price will reach the upper liquidation zone within the next 30 minutes.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![LightGBM](https://img.shields.io/badge/model-LightGBM-brightgreen.svg)](https://lightgbm.readthedocs.io)
[![Django](https://img.shields.io/badge/backend-Django%20Channels-092E20.svg)](https://channels.readthedocs.io)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

---

## Overview

The system streams live market data from Binance Futures, computes 39 engineered features every 5 minutes, and runs a LightGBM classifier to generate a probability score. When the score exceeds the configurable threshold, a signal is fired and logged as a paper trade.

**Key metrics (benchmark on synthetic data)**

| Metric | Value |
|---|---|
| AUC-ROC | ~0.82 |
| Brier Score | ~0.14 |
| Signal threshold | 0.70 (configurable) |
| Prediction horizon | 30 minutes |

---

## Architecture

```
Binance Futures WebSocket / REST
            │
            ▼
┌───────────────────┐
│   collector/      │  Layer 1 — 6 async streams (kline, liquidation,
│                   │            order book, agg trade, OI, funding)
└────────┬──────────┘
         │  data/raw/*.csv
         ▼
┌───────────────────┐
│  feature_engine/  │  Layer 2+3 — 39 features + forward-looking label
│                   │             (runs every 5 min via cron/loop)
└────────┬──────────┘
         │  data/processed/features_5m.csv
         ▼
┌───────────────────┐
│      ml/          │  Layer 4 — LightGBM classifier
│  train.py         │            TimeSeriesSplit · early stopping
│  predict.py       │            saved to ml/artifacts/lgb_model.pkl
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│    signal/        │  Layer 5 — inference loop + paper trading log
└────────┬──────────┘
         │  data/processed/paper_trades.csv
         ▼
┌───────────────────┐
│    server/        │  Layer 6 — Django + Channels WebSocket dashboard
│  (dashboard)      │            LightweightCharts · real-time price feed
└───────────────────┘
```

All layers communicate through CSV files — no message broker required.

---

## Project Structure

```
btc-liq-predictor/
├── collector/              # Layer 1 — Binance WebSocket collectors
│   ├── main.py             #   Entry point (asyncio multi-stream)
│   ├── ws_kline.py
│   ├── ws_liquidation.py
│   ├── ws_orderbook.py
│   ├── ws_aggtrade.py
│   ├── rest_oi.py
│   ├── rest_funding.py
│   └── db.py               #   CSV append helper
│
├── feature_engine/         # Layer 2+3 — Feature extraction + labelling
│   ├── run.py              #   Main loop (every 5 min)
│   ├── build_features.py
│   ├── label_builder.py
│   ├── load_data.py
│   └── feat_*.py           #   Per-source feature modules
│
├── ml/                     # Layer 4 — Model training & inference
│   ├── train.py            #   LightGBM + TimeSeriesSplit CV
│   ├── predict.py          #   load_model() / predict_signal()
│   └── artifacts/          #   lgb_model.pkl (gitignored)
│
├── signal/                 # Layer 5 — Signal generation
│   ├── run.py              #   Inference loop
│   ├── paper_log.py        #   Paper trade logger
│   └── notifier.py         #   Telegram alerts (optional)
│
├── server/                 # Layer 6 — Web dashboard
│   ├── btc_dashboard/      #   Django project settings
│   ├── dashboard/          #   App: views, consumers, broadcaster
│   ├── static/             #   JS (LightweightCharts, app logic)
│   └── templates/
│
├── scripts/
│   └── generate_fake_data.py   # Dev: generate synthetic data + train mock model
│
├── notebooks/
│   └── model_comparison.ipynb  # Benchmark: 8 algorithms compared
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── data/                   # gitignored — created at runtime
│   ├── raw/
│   └── processed/
│
├── docker/
│   └── docker-compose.yml
├── .env.example
├── Makefile
└── pyproject.toml
```

---

## Quick Start (Development)

```bash
# 1. Clone & set up environment
git clone <repo-url>
cd btc-liq-predictor
make setup          # creates .venv + installs all dependencies

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY

# 3. Generate synthetic data + train mock model
make fake-data      # writes data/raw/, data/processed/, ml/artifacts/lgb_model.pkl

# 4. Launch dashboard
make server
# → http://localhost:8000
```

---

## Production

Each service runs independently in its own terminal or process manager:

```bash
make collector      # Stream market data from Binance → data/raw/
make features       # Compute features every 5 min    → data/processed/
make signal         # Run inference + log paper trades
make server         # Serve dashboard
```

Recommended: collect at least **7–14 days** of real data before training the production model (`make train`).

---

## ML Model

**Algorithm:** LightGBM (`LGBMClassifier`)

**Why LightGBM:** Benchmarked against 8 algorithms (XGBoost, CatBoost, Random Forest, Logistic Regression, SVM, MLP, AdaBoost, GBM) — LightGBM achieved the best AUC-ROC *and* best Brier score (calibration), making it the strongest choice for both ranking and probability estimation.

See the full benchmark: [`notebooks/model_comparison.ipynb`](notebooks/model_comparison.ipynb)

**Features (39 total):**

| Category | Features |
|---|---|
| Price | Returns over 5/15/30/60 min windows, volatility, candle patterns |
| Liquidation zones | Upper/lower zone distance, zone width |
| Order book | Bid/ask imbalance, depth ratio |
| CVD | Cumulative volume delta, delta acceleration |
| Whale activity | Large trade count, large trade volume ratio |
| Open interest | OI change rate, OI × price |
| Funding rate | Current rate, rate momentum |

**Label:** Binary — `1` if `max(high[T → T+30min]) ≥ upper_liq_zone`, else `0`

**Training:**
```bash
make train          # requires ≥ 200 labeled rows; 2,000+ recommended
```

---

## Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key |
| `BINANCE_API_KEY` | No | Needed only for private endpoints |
| `BINANCE_API_SECRET` | No | Needed only for private endpoints |
| `TELEGRAM_BOT_TOKEN` | No | Signal alerts via Telegram |
| `TELEGRAM_CHAT_ID` | No | Target chat for alerts |
| `SIGNAL_THRESHOLD` | No | Prediction threshold (default: `0.70`) |

---

## Development

```bash
make test           # Full test suite (unit + integration)
make test-unit      # Unit tests only
make lint           # Flake8
make clean          # Remove cache files
```

---

## Docker

```bash
docker compose -f docker/docker-compose.yml up -d
```

Four services: `collector`, `feature_engine`, `signal`, `dashboard`. Shared volumes: `data/` and `ml/artifacts/`.

---

## Roadmap

- [ ] Accumulate 7–14 days of real Binance data
- [ ] Retrain LightGBM on real labeled data (target: AUC ≥ 0.75 on live data)
- [ ] Add Optuna hyperparameter tuning
- [ ] Walk-forward backtesting module
- [ ] Live PnL tracking (replace paper trading with simulated fills)
- [ ] Multi-symbol support (ETH, SOL)

---

## License

MIT
