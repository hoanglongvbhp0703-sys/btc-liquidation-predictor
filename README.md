# BTC Cascade Liquidation Predictor

A machine learning system that predicts **cascade liquidation events** in BTC Futures (Binance USDS-M) to identify short-term trading opportunities.

---

## Core Idea

When many futures positions are force-liquidated simultaneously (a "cascade"), BTC price moves sharply in one direction within 1–3 minutes. This system predicts the probability of a cascade occurring in the next 1–3 minutes and fires a paper trade signal when confidence is high enough.

**Key constraint:** Cascade median move (~0.029%) is smaller than taker fee (0.10%), so only **maker orders** are viable.

---

## System Architecture — 5 Layers

```
Layer 1   collector/main.py            7 Binance streams → raw CSVs
Layer 2   feature_engine/run.py        Build 38 features every 1 min → features_1m.csv
Layer 3   feature_engine/label_builder.py   Label cascade events (3 horizons × 2 directions)
Layer 4   ml/train.py + auto_train.py  Ensemble RF+LR+XGB, auto-retrain every 60 min
Layer 5   signal/run.py                Predict every 10s (deduped to 1×/min), fire paper trade
```

### Live Services (tmux session `btc`)

| Window | Script | Role | Interval |
|--------|--------|------|----------|
| 0 | `signal/run.py` | Predict + paper trade | 10s poll, 1 predict/min |
| 1 | `collector/main.py` | 7 Binance WS/REST streams | real-time |
| 2 | `feature_engine/run.py` | Features + labels | 1 min |
| 3 | `server/manage.py` | Django dashboard | http://localhost:8000 |
| 4 | `ml/auto_train.py` | Auto retrain | 60 min |
| 5 | `scripts/monitor_short.py` | Live SHORT signal monitor | 60s refresh |
| 6 | `scripts/signal_validator.py` | Signal validator (no cooldown) | 10s |

---

## How to Run

### Prerequisites

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Start all services

```bash
# Create tmux session
tmux new-session -s btc -n signal -d
tmux new-window -t btc -n collector
tmux new-window -t btc -n features
tmux new-window -t btc -n server
tmux new-window -t btc -n auto_train
tmux new-window -t btc -n monitor
tmux new-window -t btc -n validator

# Start each service
tmux send-keys -t btc:0 "python3 signal/run.py" Enter
tmux send-keys -t btc:1 "python3 collector/main.py" Enter
tmux send-keys -t btc:2 "python3 feature_engine/run.py" Enter
tmux send-keys -t btc:3 "python3 server/manage.py runserver 0.0.0.0:8000" Enter
tmux send-keys -t btc:4 "python3 ml/auto_train.py" Enter
tmux send-keys -t btc:5 "python3 scripts/monitor_short.py" Enter
tmux send-keys -t btc:6 "python3 scripts/signal_validator.py" Enter
```

### First-time setup (no model yet)

```bash
# Collect at least 4 hours of data, then:
python3 feature_engine/run.py      # build features
python3 ml/train.py                # train initial model
python3 signal/run.py              # start signal engine
```

### Configuration

All parameters live in `config.py` (override via environment variables):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SIGNAL_THRESHOLD` | 0.65 | Minimum cascade probability to fire signal |
| `CASCADE_TP_PCT` | 0.12% | Take-profit distance |
| `CASCADE_SL_PCT` | 0.12% | Stop-loss distance |
| `SIGNAL_COOLDOWN` | 900s | Per-direction cooldown between signals |
| `MAX_TTC` | 2.0 min | Max predicted time-to-cascade |
| `USE_MAKER` | true | Use maker limit orders |
| `MAKER_OFFSET_PCT` | 0.005% | Maker order offset from market price |

---

## Model

### Ensemble: RF + LR + XGB

- **6 cascade models:** `ens_cascade_{long/short}_{1/2/3}m.pkl`
- **6 TP-hit models:** `ens_tp_hit_{long/short}_{1/2/3}m.pkl` *(not yet in production — needs 50k+ rows)*
- Artifacts: `ml/artifacts/`

### Label Definition

```
cascade_long_Xm  = 1  if  sum(liq_short_usd[T → T+Xm]) > 3× baseline/min × X
cascade_short_Xm = 1  if  sum(liq_long_usd[T → T+Xm])  > 3× baseline/min × X
```

Baseline uses expanding lookback: 30m → 2h → 6h → 24h → global median.

### Model Performance (as of 2026-05-30, 17,968 rows, 303 auto-retrains)

| Target | AUC |
|--------|-----|
| cascade_long_1m | 0.784 |
| cascade_short_1m | 0.747 |
| cascade_short_2m | 0.698 |
| cascade_long_2m | 0.665 |
| cascade_short_3m | 0.654 |
| cascade_long_3m | 0.639 |
| **Average** | **0.698** |

AUC stabilized around 0.698–0.702 with > 14k rows.

---

## 38 Input Features

Built every 1 minute from 7 live data streams:

| Category | Features |
|----------|----------|
| Price & volatility | return_1m/5m/15m, high_low_range, volatility |
| Liquidations | liq_long/short_usd (1m/5m/15m/1h), liq_total, liq_ratio |
| CVD (Cumulative Volume Delta) | cvd_1m/5m/15m/1h, cvd_acceleration |
| Order book | bid/ask imbalance, spread, top-5 depth |
| Open interest | oi_change_1m/5m/15m, oi_total |
| Funding rate | funding_rate, funding_long/short_heavy flag |
| Whale trades | whale_buy/sell_usd, whale_net |

---

## Live Performance

### Signal Validator (no cooldown — cleanest precision metric)

*Period: 2026-05-26 → 2026-05-30 (after maker entry fix)*

| Direction | Fires | TP | FP | Precision |
|-----------|-------|----|----|-----------|
| SHORT | 42 | 25 | 17 | **59.5%** |
| Overall | 58 | 34 | 23 | 59.6% |

### Paper Trading (15-min cooldown + open-trade filter)

*Period: 2026-05-26 → 2026-05-30*

| Direction | Fires | WIN | LOSS | WR | PnL |
|-----------|-------|-----|------|----|-----|
| **SHORT** | 40 | 18 | 2 | **90.0%** | **+1.92%** |
| LONG | 27 | 2 | 15 | 12% | -1.56% |
| **Combined** | 67 | 20 | 17 | **54.1%** | +0.36% |

> SHORT WR of 90% is promising but based on n=20 resolved trades — 95% CI: [70%, 97%]. Requires n≥50 to draw conclusions. EXPIRED rate is 34% (TP/SL ±0.12% tight relative to 3-min price move).

### All-Time Summary (2026-05-13 → 2026-05-30)

| Metric | Value |
|--------|-------|
| Total paper trades fired | 219 |
| Resolved win rate | 24.6% |
| Total PnL | -22.45% |
| EXPIRED | 78 (36%) |

> All-time WR dragged down by LONG trades (7.6% WR, dominant in early downtrend phase). SHORT-only WR all-time: 50% (8/16 resolved).

---

## Key Engineering Decisions

| Decision | Reason |
|----------|--------|
| Maker orders only | Cascade median move (0.029%) < taker fee (0.10%) |
| Ensemble RF+LR+XGB | Single RF overfits; LR adds calibration; XGB adds non-linearity |
| No hard liquidation filter | `liq_total_1m` is feature #3 — model learns threshold internally |
| Deduped predict (1×/min) | Features update every 60s; 10s poll gives ≤10s latency, no redundant inference |
| Parallel LONG/SHORT predict | `ThreadPoolExecutor(max_workers=2)` — RF/XGB release GIL; 1,300ms → 500ms |
| SHORT entry below market | Cascade = immediate price drop; entry at `price × (1 − 0.005%)` fills when `low ≤ entry` |
| Adaptive sleep | `sleep(max(0, 10s − elapsed))` ensures consistent 10s cycle regardless of predict duration |

---

## Directory Structure

```
config.py                    Single source of truth — all constants and paths
collector/
  main.py                    Entry: 7 async Binance streams
  ws_*.py / rest_*.py        Individual stream handlers (liquidations, klines, OB, etc.)
feature_engine/
  run.py                     Entry: builds features + labels every 1 min
  build_features.py          build_feature_row() — 38 features
  label_builder.py           build_pending_labels(), build_tp_labels() (incremental O(new))
ml/
  train.py                   Train 6 cascade + 6 TP-hit ensemble models
  auto_train.py              60-min retrain loop
  predict.py                 load_model(), predict_cascade_signal(), predict_all()
  artifacts/                 *.pkl models, meta.json, train_history.json
signal/
  run.py                     Entry: predict loop, cooldown, paper trade logging
  paper_log.py               log_signal(), check_outcomes() via klines_1s
  notifier.py                Telegram notifications
scripts/
  signal_validator.py        Validate signals without cooldown → signal_outcomes.csv
  monitor_short.py           Live SHORT monitor (events from script-start only)
server/                      Django dashboard — http://localhost:8000
data/
  features_1m.csv            Main ML dataset (17,968 rows, 09/05 → present)
  paper_trades.csv           Paper trading log
  signal_outcomes.csv        Validator log (ground truth for out-of-sample precision)
  klines_1s.csv              1-second candles for outcome verification
  liquidations.csv           Raw liquidation events from Binance
```

---

## Roadmap

### Immediate (no extra data needed)
- Disable LONG signals — WR 7.6%, not viable in current regime

### When SHORT validator reaches n=50 resolved
- Re-evaluate precision; consider raising threshold to 0.70 if precision ≥ 75%

### When 30 days of data collected
- Walk-forward backtest before any capital allocation
- Assess performance across multiple market regimes (bull/bear/sideways)

### Long-term (50k+ rows)
- Train TP-hit models (positive rate currently 1.5–3.8%)
- Optuna hyperparameter tuning
- DL models (GJR-GARCH+GRU, Bi-LSTM) — currently AUC 0.653 vs Ensemble 0.698
- Add Binance API execution (~50 lines once precision is validated)

---

## Go-Live Criteria (not yet met)

| Condition | Target | Current |
|-----------|--------|---------|
| SHORT precision (validator) | ≥ 75% sustained | 59.5% |
| SHORT resolved signals | ≥ 50 | 42 |
| Data coverage | ≥ 30 days, multiple regimes | 21 days, sideways/downtrend |
| **Status** | | ❌ Not ready for live capital |

---

## Known Limitations

1. **21 days of data, one regime** — model has not seen a bull market or high-volatility period
2. **EXPIRED 34%** — TP/SL ±0.12% tight; price often doesn't move enough in 3 minutes
3. **LONG not viable** — 7.6% WR in downtrend; to be re-evaluated in bull regime
4. **TP-hit models not in production** — needs 50k+ rows to learn 1.5–3.8% positive rate
5. **SOL pipeline** — separate tmux session `sol`, early stage, insufficient data
