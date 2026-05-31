# BTC Cascade Liquidation Predictor

> Real-time machine learning system that predicts BTC Futures cascade liquidation events and generates short-term trading signals.

---

## Purpose

Cascade liquidations occur when a chain of forced position closures in BTC Futures triggers a sharp, directional price move within 1–3 minutes. This system detects the early signs of a cascade before it happens and fires a trade signal with enough lead time to enter a maker limit order — keeping execution costs below the profit margin.

**Core constraint:** Cascade median price move (~0.029%) is smaller than the taker fee (0.10%), so the system is designed exclusively around **maker orders** to remain viable.

---

## Description

A fully automated, 5-layer pipeline running 24/7 on a Linux server:

1. **Data collection** — 7 parallel Binance WebSocket/REST streams ingest liquidations, order book, trades, open interest, funding rate, and 1-second klines in real time
2. **Feature engineering** — 38 market microstructure features are computed every 60 seconds from the raw streams
3. **Labeling** — cascade events are labeled across 3 time horizons (1m / 2m / 3m) for both LONG and SHORT directions
4. **Model training** — an ensemble of Random Forest + Logistic Regression + XGBoost is auto-retrained every 60 minutes as new labeled data arrives
5. **Signal engine** — runs every 10 seconds, predicts cascade probability, applies cooldown logic, and logs paper trades for performance tracking

A Django web dashboard provides real-time visibility into signals, model accuracy, and paper trading P&L.

---

## Features

- **Real-time cascade prediction** — ensemble model outputs probability across 1m / 2m / 3m horizons; signal fires when `max_prob ≥ 0.65` and estimated time-to-cascade `≤ 2 min`
- **Maker-order simulation** — paper trades simulate limit-order fills using 1-second kline data; entry offset 0.005% from market price
- **Auto-retrain loop** — model retrains every 60 minutes on newly labeled rows; no manual intervention required
- **Signal validator** — parallel process validates every signal without cooldown constraints, providing unbiased precision measurement
- **Live monitor** — SHORT signal monitor shows real-time TP/FP/FN events from script start (not historical backtest)
- **Parallel inference** — LONG and SHORT predictions run concurrently via `ThreadPoolExecutor`; latency reduced from 1,300ms to 500ms
- **Deduped predict loop** — skips inference when feature row is unchanged; each 60-second feature window is predicted exactly once
- **Telegram notifications** — instant alert on signal fire with entry, TP, SL, and estimated cascade timing
- **Django dashboard** — web UI at `localhost:8000` showing live trades, win rate, P&L, and model stats

---

## Tech Stack

| Category | Technology |
|----------|------------|
| **Language** | Python |
| **ML / Data** | scikit-learn · NumPy · Pandas |
| **Web dashboard** | Django |
| **Data storage** | CSV datasets · SQLite |
| **Version control** | git |
| **OS** | Linux |

---

## Live Performance (2026-05-26 → 2026-05-30)

| Metric | Value |
|--------|-------|
| Model avg AUC | **0.698** (6 models) |
| Auto-retrains | **303** since inception |
| Training rows | **17,968** (21 days) |
| SHORT win rate (paper) | **90%** — 18/20 resolved |
| SHORT P&L (paper) | **+1.92%** |
| Signal precision (validator) | **59.5%** — 25/42 SHORT TP |

> SHORT WR of 90% is based on n=20 resolved trades — 95% CI: [70%, 97%]. Needs n≥50 before drawing conclusions. System is in paper trading validation phase; not yet deployed with real capital.

---

## System Workflow

```
Binance Streams
  │  liquidations · klines · order book · aggtrades · open interest · funding · basis
  ▼
collector/main.py  ──────────────────────────────────  data/*.csv  (raw)
  ▼
feature_engine/run.py  (every 60s)
  ├─ build_features.py   →  38 features per row
  └─ label_builder.py    →  cascade_long/short_1/2/3m labels
  ▼
features_1m.csv  (17,968 rows)
  ▼
ml/auto_train.py  (every 60 min)
  └─ train.py  →  Ensemble RF + LR + XGB  →  ml/artifacts/*.pkl
  ▼
signal/run.py  (every 10s poll, 1 predict/min)
  ├─ predict.py           →  cascade probability × 6 models
  ├─ cooldown check       →  900s per direction
  ├─ has_open_trade check →  1 position per direction max
  └─ paper_log.py         →  paper_trades.csv  +  Telegram alert
  ▼
scripts/signal_validator.py  →  signal_outcomes.csv  (no cooldown, unbiased precision)
scripts/monitor_short.py     →  live SHORT TP/FP/FN display
server/manage.py             →  Django dashboard  http://localhost:8000
```

---

## Directory Structure

```
config.py                   Single source of truth — all constants and paths
collector/
  main.py                   Entry: 7 async Binance streams
feature_engine/
  run.py                    Entry: features + labels every 1 min
  build_features.py         38-feature row builder
  label_builder.py          Incremental cascade + TP-hit labeling
ml/
  train.py                  Ensemble model training (6 cascade + 6 TP-hit)
  auto_train.py             60-min retrain loop
  predict.py                Inference — predict_cascade_signal(), predict_all()
  artifacts/                *.pkl models · meta.json · train_history.json
signal/
  run.py                    Entry: predict loop, cooldown, paper trade log
  paper_log.py              Outcome verification via klines_1s.csv
  notifier.py               Telegram alerts
scripts/
  signal_validator.py       Unbiased signal precision tracker
  monitor_short.py          Live SHORT monitor (live-only events)
server/                     Django dashboard — http://localhost:8000
data/
  features_1m.csv           ML dataset (17,968 rows, 09/05 → present)
  paper_trades.csv          Paper trading log
  signal_outcomes.csv       Validator log — ground truth precision
  klines_1s.csv             1-second candles for outcome verification
```

---

## How to Run

```bash
# 1. Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Start all services in tmux
tmux new-session -s btc -n signal -d
tmux send-keys -t btc:0 "python3 signal/run.py" Enter

tmux new-window -t btc -n collector
tmux send-keys -t btc:1 "python3 collector/main.py" Enter

tmux new-window -t btc -n features
tmux send-keys -t btc:2 "python3 feature_engine/run.py" Enter

tmux new-window -t btc -n server
tmux send-keys -t btc:3 "python3 server/manage.py runserver 0.0.0.0:8000" Enter

tmux new-window -t btc -n auto_train
tmux send-keys -t btc:4 "python3 ml/auto_train.py" Enter

tmux new-window -t btc -n monitor
tmux send-keys -t btc:5 "python3 scripts/monitor_short.py" Enter

tmux new-window -t btc -n validator
tmux send-keys -t btc:6 "python3 scripts/signal_validator.py" Enter
```

### Key configuration (env vars or `config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SIGNAL_THRESHOLD` | `0.65` | Min probability to fire signal |
| `CASCADE_TP_PCT` | `0.0012` | Take-profit distance (0.12%) |
| `CASCADE_SL_PCT` | `0.0012` | Stop-loss distance (0.12%) |
| `SIGNAL_COOLDOWN` | `900` | Cooldown in seconds per direction |
| `MAX_TTC` | `2.0` | Max time-to-cascade in minutes |
| `USE_MAKER` | `true` | Use maker limit orders |

---

## Go-Live Criteria (not yet met)

| Condition | Target | Current |
|-----------|--------|---------|
| SHORT precision (validator) | ≥ 75% sustained | 59.5% |
| SHORT resolved signals | ≥ 50 | 42 |
| Data coverage | ≥ 30 days, multiple regimes | 21 days, sideways/downtrend |
| **Status** | | ❌ Paper trading only |
