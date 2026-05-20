# SESSION SUMMARY — BTC Cascade Liquidation Predictor

## Tổng quan dự án

Hệ thống dự đoán cascade liquidation BTC Futures (Binance) để tìm cơ hội trade.
- **Model:** Ensemble RF+LR+XGB (3 horizons: 1m/2m/3m) × 2 directions (LONG/SHORT) = 6 artifacts
- **Data:** 12,942 rows (2026-05-09 → 2026-05-20, 11 ngày), 1 market regime
- **Pipeline:** 7 services chạy 24/7 trên tmux session `btc`

---

## Trạng thái hệ thống (20/05/2026)

```
tmux session 'btc':
  signal    (win 0)  ✅ Inference mỗi 10s, threshold=0.65, cooldown 900s/direction
  collector (win 1)  ✅ 7 streams Binance (WS + REST)
  features  (win 2)  ✅ Feature engineering mỗi 2 phút, 12,942 rows
  server    (win 5)  ✅ Dashboard http://localhost:8000
  auto_train(win 10) ✅ Retrain Ensemble mỗi 1 giờ (109 lần, AUC ổn định 0.7185)
  monitor   (win 13) ✅ SHORT monitor terminal
  validator (win 14) ✅ Signal TP/FP tracker

tmux session 'sol':  ✅ SOL pipeline chạy song song (4 windows)
```

---

## Model hiện tại (retrain lần cuối 20/05 07:46 UTC)

### AUC tại thời điểm 20/05/2026

| Target | AUC | Precision @0.65 | Recall |
|---|---|---|---|
| long_1m | 0.7492 | 0.647 | 0.083 |
| long_2m | 0.6772 | 0.438 | 0.050 |
| long_3m | 0.6418 | 0.455 | 0.035 |
| short_1m | 0.7743 | 0.487 | 0.161 |
| short_2m | 0.7374 | 0.390 | 0.110 |
| short_3m | 0.7310 | 0.483 | 0.088 |
| **Avg** | **0.7185** | | |

AUC tăng từ 0.7085 (19/05) → **0.7185** (20/05) nhờ thêm data. Đã ổn định 4 lần train liên tiếp.

---

## Signal Accuracy — Live performance (20/05/2026)

### Signal Validator (live, tính từ lúc bắt đầu track)

| Direction | Total | TP | FP | Pending | Precision |
|---|---|---|---|---|---|
| SHORT | 24 | 9 | 14 | 1 | **39.1%** |
| LONG | 18 | 7 | 10 | 1 | **41.2%** |

### Monitor SHORT (batch backtest toàn bộ historical)
- Precision=**86%** trên 556 signals — đây là retroactive scoring, không phải live.

---

## Paper Trading (20/05/2026)

| | n | WIN | LOSS | EXPIRED | PnL |
|---|---|---|---|---|---|
| LONG | 91 | 5 (5%) | 65 (71%) | 21 | **-24.9%** |
| SHORT | 30 | 3 (10%) | 0 (0%) | 27 | **+0.3%** |

**Vấn đề cốt lõi:** Cascade BTC median 0.029% < taker fee round-trip 0.10% → LONG không khả thi với market order.

---

## Config hiện tại (single source of truth: config.py)

| Parameter | Giá trị | Override env var |
|---|---|---|
| `SIGNAL_THRESHOLD` | **0.65** | `SIGNAL_THRESHOLD` |
| `CASCADE_TP_PCT` | **0.12%** | `CASCADE_TP_PCT` |
| `CASCADE_SL_PCT` | **0.12%** | `CASCADE_SL_PCT` |
| `SIGNAL_COOLDOWN` | **900s** | `SIGNAL_COOLDOWN` |
| `MAX_TTC` | **2.0m** | `MAX_TTC` |
| `LIQ_FILTER_USD` | **$500k** | `LIQ_FILTER_USD` |
| `USE_MAKER` | **true** | `USE_MAKER` |
| `MAKER_OFFSET_PCT` | **0.005%** | `MAKER_OFFSET_PCT` |
| Model type | **Ensemble RF+LR+XGB** | — |

---

## Tasks đã hoàn thành (20/05/2026)

### Refactor: Loại bỏ hardcode + file thừa ✅

**Xóa file thừa:**
- `collector/rest_funding.py` + `rest_basis.py` → thay bằng `rest_premium_index.py`

**config.py — thêm trading constants:**
- `CASCADE_TP_PCT`, `CASCADE_SL_PCT`, `SIGNAL_COOLDOWN`, `MAX_TTC` (tất cả override được qua env var)

**Các file đã fix hardcode:**
- `ml/predict.py`: dùng `ML_DIR`, `CASCADE_TP_PCT/SL`, `HORIZONS` từ config
- `signal/run.py`: `COOLDOWN_FILE` dùng `DATA_DIR`, `SIGNAL_COOLDOWN`/`MAX_TTC` từ config
- `signal/notifier.py`: direction/symbol động thay vì hardcode "BTC LONG"
- `collector/main.py`: health_monitor dùng `premium_index.csv`, banner "7 streams"
- `scripts/monitor_short.py`: dùng `ML_DIR` từ config
- `scripts/rebuild_features.py`: xóa path `/home/coder` hardcode, hỗ trợ `premium_index.csv`

### Fix UI bugs ✅

- `signal.js`: TP/SL % label tính động từ signal data (trước: hardcode +0.8%/-0.5%)
- `signal.js`: CVD chart chỉ cộng khi delta thực sự thay đổi (trước: phình 60x)
- `data_reader.py`: filter liquidation dùng `SYMBOL` từ config (trước: hardcode BTCUSDT)
- `broadcaster.py`: `MODEL_FILE` dùng `ML_DIR` từ config (multi-symbol support)

### SOL Pipeline ✅

- `scripts/start_sol.sh`: `bash scripts/start_sol.sh` → tmux session `sol`
- Data: `data/sol/` | Models: `ml/artifacts/sol/`

---

## Git commits (20/05/2026)

```
7565ca10  fix: correct UI bugs — hardcoded TP/SL labels, CVD chart, SYMBOL filter, ML_DIR
1a74ad6d  refactor: eliminate hardcodes and unused files, add SOL pipeline
```

Push lên cả 2 remote:
- `origin`: git.nsts.com.vn/hoanglongvbhp0703/hoanglongvbhp
- `github`: github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor

---

## Điều kiện để live trade BTC (chưa đạt)

1. ❌ Precision ≥ 75% sustained (hiện 39–41% live, n=42)
2. ❌ 50+ resolved signals ở thr≥0.65 (hiện 42)
3. ❌ 30+ ngày data, nhiều market regime (hiện 11 ngày, 1 regime)

---

## Việc cần làm theo thứ tự ưu tiên

1. **[ĐANG CHẠY]** Tích lũy data — pipeline 24/7, mỗi ngày +~1,440 rows
2. **[TIẾP THEO]** Khi có 50+ resolved signals → đánh giá lại precision
3. Xem xét trigger-based retraining khi data đủ lớn (>50k rows):
   - Data volume trigger: retrain khi có thêm 500 rows mới
   - Performance drift trigger: retrain khi live precision < 0.55
4. Khi đủ điều kiện: thêm Binance API execution (~50 dòng code)

---

## Giới hạn thực tế

- **11 ngày data, 1 market regime** (sideways/downtrend) — chưa thấy bull/high-vol
- **n=42 live signals** — CI quá rộng để kết luận precision
- **Cascade BTC median 0.029% < taker fee 0.10%** — edge âm với market order
- **LONG thua liên tiếp** dù prob cao → không trade LONG BTC với config hiện tại
- **SHORT: 0 LOSS toàn lịch sử paper trade** nhưng n nhỏ, cần thêm data
