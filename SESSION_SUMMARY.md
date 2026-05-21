# SESSION SUMMARY — BTC Cascade Liquidation Predictor

## Tổng quan dự án

Hệ thống dự đoán cascade liquidation BTC Futures (Binance) để tìm cơ hội trade.
- **Model:** Ensemble RF+LR+XGB (3 horizons: 1m/2m/3m) × 2 directions (LONG/SHORT) = 6 artifacts
- **Data:** 13,858 rows (2026-05-09 → 2026-05-21, 12 ngày), 1 market regime
- **Pipeline:** 7 services chạy 24/7 trên tmux session `btc`

---

## Trạng thái hệ thống (21/05/2026)

```
tmux session 'btc':
  signal    (win 0)  ✅ Inference mỗi 10s, threshold=0.65, cooldown 900s/direction
  collector (win 1)  ✅ 7 streams Binance (WS + REST)
  features  (win 2)  ✅ Feature engineering mỗi 1 phút, 13,858 rows
  server    (win 5)  ✅ Dashboard http://localhost:8000
  auto_train(win 10) ✅ Retrain Ensemble mỗi 1 giờ (109+ lần, AUC ổn định 0.7185)
  monitor   (win 13) ✅ SHORT monitor terminal
  validator (win 14) ✅ Signal TP/FP tracker

tmux session 'sol':  ✅ SOL pipeline chạy song song (4 windows)
```

---

## Model hiện tại (retrain lần cuối 21/05 16:37 UTC)

| Target | AUC |
|---|---|
| long_1m | 0.7492 |
| long_2m | 0.6772 |
| long_3m | 0.6418 |
| short_1m | 0.7743 |
| short_2m | 0.7374 |
| short_3m | 0.7310 |
| **Avg** | **0.7185** |

AUC ổn định 0.7185 qua nhiều lần train liên tiếp — model đã hội tụ với data hiện tại.

---

## Config hiện tại (single source of truth: config.py)

| Parameter | Giá trị | Override |
|---|---|---|
| `SIGNAL_THRESHOLD` | **0.65** | env var |
| `CASCADE_TP_PCT` | **0.120%** | env var |
| `CASCADE_SL_PCT` | **0.120%** | env var |
| `SIGNAL_COOLDOWN` | **900s (15min)** | env var |
| `MAX_TTC` | **2.0m** | env var |
| `LIQ_FILTER_USD` | **$500,000** | env var |
| `USE_MAKER` | **true** | env var |
| `MAKER_OFFSET_PCT` | **0.005%** | env var |

TP/SL xác nhận đúng từ trades thực tế: entry±0.120%, R:R=1:1, order_type=maker.

---

## Signal Accuracy — Live performance (21/05/2026)

### Signal Validator (live, n=42 tổng)

| Direction | Resolved | TP | FP | Pending | Precision |
|---|---|---|---|---|---|
| SHORT | 23 | 9 | 14 | 1 | **39.1%** |
| LONG | 17 | 7 | 10 | 1 | **41.2%** |

### Monitor SHORT (batch backtest toàn bộ historical)
Precision=**86%** / 556 signals — retroactive scoring trên 13k rows lịch sử, không phải live.

---

## Paper Trading (21/05/2026, 123 closed)

| | n | WIN | LOSS | EXPIRED | UNFILLED | PnL |
|---|---|---|---|---|---|---|
| LONG | 91 | 5 (5%) | 65 (71%) | 20 | 1 | **-24.88%** |
| SHORT | 32 | 3 (9%) | 0 (0%) | 29 | 0 | **+0.35%** |
| **Tổng** | **123** | **8** | **65** | **49** | **1** | **-24.53%** |

**Vấn đề cốt lõi — tại sao thua dù model tốt:**
```
Cascade BTC median move = 0.029% trong 1 phút
Taker fee round-trip    = 0.10%
→ 90% cascade không đủ lớn để thắng fee với market order
→ Maker fee round-trip  = 0.02% → viable, đang dùng USE_MAKER=true
```
- **LONG: không trade** — 7/7 LOSS liên tiếp dù prob 0.79–0.85
- **SHORT: breakeven** — 0 LOSS toàn lịch sử, cần thêm data

---

## Thay đổi session này (20–21/05/2026)

### 1. Refactor: loại bỏ hardcode + file thừa ✅

**Xóa file thừa:**
- `collector/rest_funding.py` + `rest_basis.py` → đã thay bằng `rest_premium_index.py`

**config.py — thêm trading constants (override qua env var):**
- `CASCADE_TP_PCT`, `CASCADE_SL_PCT`, `SIGNAL_COOLDOWN`, `MAX_TTC`

**Các file đã fix hardcode:**

| File | Vấn đề | Fix |
|---|---|---|
| `ml/predict.py` | TP/SL/HORIZONS hardcode, SAVED_DIR sai | Dùng `ML_DIR`, constants từ config |
| `signal/run.py` | COOLDOWN_FILE sai dir, COOLDOWN/MAX_TTC hardcode | Dùng `DATA_DIR`, import từ config |
| `signal/notifier.py` | "BTC LONG SIGNAL" hardcode | Dynamic theo `signal['direction']` |
| `collector/main.py` | health_monitor check file cũ, banner "8 streams" | Dùng `premium_index.csv`, "7 streams" |
| `scripts/monitor_short.py` | ARTIFACTS_DIR không dùng ML_DIR | Dùng `ML_DIR` từ config |
| `scripts/rebuild_features.py` | Hardcode `/home/coder`, không hỗ trợ premium_index | Dùng ROOT từ `__file__`, auto-detect |

### 2. Fix UI bugs ✅

| Bug | File | Trước | Sau |
|---|---|---|---|
| TP/SL % label sai | `signal.js:247` | Hardcode `+0.8%`/`-0.5%` | Tính động từ signal.entry/tp/sl |
| CVD chart phình 60x | `signal.js:47` | Cộng delta mỗi 1s tick | Chỉ cộng khi feature thực sự thay đổi |
| BTCUSDT hardcode | `data_reader.py:154` | `== "BTCUSDT"` | `== SYMBOL` từ config |
| MODEL_FILE sai path | `broadcaster.py:24` | `ROOT_DIR/ml/artifacts` | `ML_DIR` từ config |

### 3. Fix bug paper_trades.csv ✅

File bị mixed format: 121 rows cũ (13 cột, thiếu `order_type`) + 2 rows mới (14 cột).
Đã backfill `order_type=market` cho rows cũ, chuẩn hoá header thành 14 cột.

### 4. SOL Pipeline ✅

```bash
bash scripts/start_sol.sh   # → tmux session 'sol'
```
Data: `data/sol/` | Models: `ml/artifacts/sol/`

---

## Git commits session này

```
ff9c7005  docs: update SESSION_SUMMARY.md to 20/05/2026
7565ca10  fix: correct UI bugs — hardcoded TP/SL labels, CVD chart, SYMBOL filter, ML_DIR
1a74ad6d  refactor: eliminate hardcodes and unused files, add SOL pipeline
```

Push lên cả 2 remote:
- `origin` : git.nsts.com.vn/hoanglongvbhp0703/hoanglongvbhp
- `github` : github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor

---

## Kiến thức thảo luận session này

### Trigger-based retraining vs Schedule-based
- **Hiện tại (schedule 1h):** đúng cho giai đoạn bootstrap ít data
- **Trigger-based** (dùng khi data đủ lớn ~2 tháng):
  - *Data volume trigger*: retrain khi có thêm 500 rows mới
  - *Performance drift trigger*: retrain khi live precision < 0.55
  - *Market regime trigger*: retrain khi volatility tăng đột biến ×2
- Auto_train đã có `check_stable()` (PATIENCE=3, MIN_DELTA=0.001) nhưng bị tắt có chủ ý — nên chuyển sang giãn interval thay vì dừng hẳn

---

## Điều kiện để live trade BTC (chưa đạt)

1. ❌ Precision ≥ 75% sustained (hiện 39–41%, n=42)
2. ❌ 50+ resolved signals ở thr≥0.65 (hiện 42)
3. ❌ 30+ ngày data, nhiều market regime (hiện 12 ngày, 1 regime)

---

## Việc cần làm theo thứ tự ưu tiên

1. **[ĐANG CHẠY]** Tích lũy data — pipeline 24/7, ~1,440 rows/ngày
2. **[GẦN ĐẠT]** 50+ resolved signals — hiện 42, cần thêm ~1–2 ngày
3. Đánh giá lại precision khi đủ 50+ signals
4. Xem xét adaptive interval cho auto_train khi data > 50k rows
5. Khi đủ điều kiện: thêm Binance API execution (~50 dòng code)

---

## Giới hạn thực tế

- **12 ngày data, 1 market regime** (sideways/downtrend) — chưa thấy bull/high-vol
- **n=42 live signals, n=40 resolved** — CI quá rộng để kết luận precision
- **Cascade BTC median 0.029% < taker fee 0.10%** — chỉ viable với maker orders
- **LONG: không trade** dù prob cao — cascade quá nhỏ so với fee
- **SHORT: 0 LOSS paper trade** — promising nhưng cần thêm n
