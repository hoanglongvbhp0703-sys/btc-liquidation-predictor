# SESSION SUMMARY — BTC Cascade Liquidation Predictor

## Tổng quan dự án

Hệ thống dự đoán cascade liquidation BTC Futures (Binance) để tìm cơ hội trade.
- **Model:** Ensemble RF+LR+XGB (3 horizons: 1m/2m/3m) × 2 directions (LONG/SHORT) = 6 CASCADE artifacts + 6 TP-hit artifacts
- **Data:** 15,116 rows (2026-05-14 → 2026-05-24, ~10 ngày), 1 market regime (sideways/downtrend)
- **Pipeline:** 7 services BTC + 4 services SOL chạy 24/7

---

## Trạng thái hệ thống (24/05/2026 ~05:35 UTC)

```
tmux session 'btc':
  signal    (win 0)  ✅ Predict mỗi 10s — liq filter ĐÃ XOÁ, model tự quyết
  collector (win 1)  ✅ 7 streams Binance (WS + REST)
  features  (win 2)  ✅ Feature engineering mỗi 1 phút, 15,116 rows
  server    (win 3)  ✅ Dashboard http://localhost:8000
  auto_train(win 4)  ✅ Retrain mỗi 60 phút, avg AUC=0.7045
  monitor   (win 5)  ✅ Running
  validator (win 6)  ✅ Running (fixed: dùng ensemble đầy đủ RF+LR+XGB)

tmux session 'sol':  ✅ SOL pipeline (4 windows)
```

---

## Model hiện tại (retrain 24/05 ~05:06 UTC, 15,116 rows)

| Target | CASCADE AUC | TP-hit AUC |
|---|---|---|
| short_1m | **0.7617** | 0.6919 |
| short_2m | **0.7055** | 0.6426 |
| short_3m | 0.6626 | 0.6251 |
| long_1m  | **0.7735** | 0.7165 |
| long_2m  | 0.6778 | 0.6537 |
| long_3m  | 0.646  | 0.625  |
| **Avg**  | **0.7045** | **0.6591** |

AUC avg tăng nhẹ từ 0.700 → 0.7045 sau thêm ~350 rows mới.
TP-hit models lưu tại `ml/artifacts/ens_tp_hit_*.pkl`, chưa dùng production (cần 50k+ rows).

---

## Config hiện tại (single source of truth: config.py)

| Parameter | Giá trị | Ghi chú |
|---|---|---|
| `SIGNAL_THRESHOLD` | **0.65** | env var |
| `CASCADE_TP_PCT` | **0.120%** | env var |
| `CASCADE_SL_PCT` | **0.120%** | env var |
| `SIGNAL_COOLDOWN` | **900s (15min)** | env var |
| `MAX_TTC` | **2.0m** | env var |
| `USE_MAKER` | **true** | env var |
| `MAKER_OFFSET_PCT` | **0.005%** | env var |
| ~~`LIQ_FILTER_USD`~~ | ~~$500,000~~ | **XOÁ ngày 23/05** |

---

## Paper Trading (24/05/2026 ~05:35 UTC)

| | n | WIN | LOSS | EXPIRED | UNFILLED | Precision (resolved) | PnL |
|---|---|---|---|---|---|---|---|
| LONG  | 97 | 5  | 68 | 24 | 0 | **7%** (n=73) | **-25.23%** |
| SHORT | 37 | 3  | 3  | 29 | 2 | **50%** (n=6) | **-0.03%** |
| **Tổng** | **134** | **8** | **71** | **53** | **2** | — | **-25.26%** |

### Signal Validator (ensemble fix, 24/05)
| | Signals | TP | FP | PENDING | Precision |
|---|---|---|---|---|---|
| SHORT | 28 | 12 | 16 | 0 | **42.9%** |
| LONG  | 22 | 9  | 12 | 1 | **42.9%** |
| **Total** | **50** | **21** | **28** | **1** | **42.9%** |

Validator precision (42.9%) thấp hơn paper_trades SHORT precision (50%) vì validator không có cooldown — bắt nhiều tín hiệu hơn, bao gồm cả false positives từ cùng 1 event.

### Sau khi bỏ liq filter (23/05 10:00 → 24/05 05:35, ~19h)
- paper_trades: 7 trades mới (1 SHORT + 6 LONG)
- signal_outcomes: 6 signals mới — thấp hơn kỳ vọng vì thị trường đang **sideways, liq_total_1m ≈ 0.0**
- Chưa thể đánh giá hiệu quả của việc bỏ filter — cần đợi có cascade event

---

## Tất cả thay đổi đã thực hiện (theo thứ tự)

---

### 1–11. Các thay đổi từ session 20–22/05 ✅
*(Giữ nguyên — xem commit `a5176074`)*

---

### 12. Phân tích signal frequency — phát hiện liq filter phản tác dụng ✅ (23/05)

**Phát hiện:**
- `liq_total_1m` là feature **#3 quan trọng nhất** trong RF (importance=0.062)
- Model đã tự học liq → hard filter bên ngoài là redundant và có hại

---

### 13. Xoá LIQ_FILTER_USD ✅ (23/05, commit `79375a16`)

- `config.py`: Xoá constant `LIQ_FILTER_USD`
- `signal/run.py`: Xoá import + block liq filter + cập nhật docstring

---

### 14. Thêm TP-hit labels + train models ✅ (23/05, commit `79375a16`)

- `feature_engine/label_builder.py`: thêm `build_tp_labels()` vectorized
- `ml/train.py`: train thêm 6 TP-hit models, in so sánh CASCADE vs TP-hit AUC

**Kết quả:** TP-hit AUC thấp hơn CASCADE (0.659 vs 0.704). Lý do: positive rate 1.5–3.8%, cần 50k+ rows.

---

### 15. Fix double write trong label_builder.py ✅ (23/05, commit `d85bb4fe`)

**Bug:** `build_pending_labels()` ghi CSV 2 lần/phút (cascade + TP).

**Fix:**
- Gọi `build_tp_labels(df_feat)` TRƯỚC `df_feat.to_csv()`
- `build_tp_labels()` chỉ write CSV khi `standalone=True` (gọi không có argument)

---

### 16. Fix recompute toàn bộ trong build_tp_labels() ✅ (23/05, commit `d85bb4fe`)

**Bug:** `build_tp_labels()` recompute cả 14k rows mỗi phút.

**Fix:**
- Dùng `np.argmax(np.isnan(existing))` để tìm row NaN đầu tiên
- Chỉ compute `[start:computable_end]` — O(new_rows) thay vì O(all_rows)
- Numpy-based forward min/max thay vì `pd.concat+shift`

**Test:** 100x no-op = 0.155s (so với O(14k) ≈ vài giây mỗi phút).

---

### 17. Fix signal_validator dùng RF thay vì ensemble ✅ (23/05, commit `4dcc213a`)

**Bug:** Validator dùng chỉ `art["models"][0]` (RF), không phải ensemble.

**Fix:** Thêm `_ensemble_prob()` — average prob RF+LR+XGB với scaler cho LR.

**Kết quả:** LONG prob tăng từ 0.178 → 0.329, consistent với paper trader.

---

### 18. Setup PreCompact hook ✅ (24/05)

**File:** `~/.claude/settings.json` + `~/.claude/precompact_summary.py`

**Chức năng:** Trước khi Claude Code auto-compact context:
1. Script đọc git state, model state, paper trading stats
2. Ghi checkpoint vào `~/.claude/projects/-home-coder/memory/project_btc_pipeline.md`
3. Output `additionalContext` JSON → Claude dùng để viết compact summary chính xác

**Note:** Không có "stop at 70% context" trong Claude Code. `autoCompactEnabled=true` compact khi context **gần đầy** (~95%). Không cấu hình được % cụ thể.

---

## Git commits

```
4dcc213a  fix: signal_validator dùng ensemble đầy đủ thay vì chỉ RF
d85bb4fe  fix: label_builder double write + recompute-all bugs
79375a16  feat: remove liq filter, add TP-hit labels, train TP-hit models (23/05/2026)
a5176074  fix: timestamp parsing, CVD chart history, test suite, performance (22/05/2026)
2b21aca8  docs: update SESSION_SUMMARY.md to 21/05/2026; fix paper_trades.csv schema
```

*(Push lên cả origin (git.nsts.com.vn) và github (github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor))*

---

## Điều kiện để live trade BTC (chưa đạt)

1. ❌ Precision ≥ 75% sustained — SHORT paper_trades 50% (n=6); validator 42.9% (n=28)
2. ❌ 50+ resolved SHORT signals — paper_trades chỉ 6 resolved; validator 28 resolved
3. ❌ 30+ ngày data, nhiều market regime — hiện ~10 ngày, 1 regime (sideways/downtrend)

**Khuyến nghị:** Không trade LONG. SHORT có thể xem xét khi validator đạt n=50+ resolved và precision ≥ 60%.

---

## Việc cần làm

### 🟡 Normal priority (đang tự chạy)

1. **[AUTO]** Tích lũy resolved SHORT trades:
   - paper_trades target: n=50 resolved (hiện n=6) — ước tính vài tuần
   - validator target: n=50 resolved (hiện n=28) — ước tính vài ngày
2. Đánh giá lại SHORT precision khi validator đạt n=50 resolved
3. Xem xét raise `SIGNAL_THRESHOLD` lên 0.70 nếu SHORT precision tiếp tục ≤ 50%
4. Đánh giá hiệu quả bỏ liq filter khi có đủ data (cần cascade event)

### 🔵 Cải thiện dài hạn

5. Khi đủ 50k+ rows: retrain TP-hit models với klines_1s (chính xác hơn close price 1m)
6. Bull market data sẽ cải thiện LONG AUC — chờ regime thay đổi
7. SOL pipeline cần thêm ~10k rows trước khi model có ý nghĩa
8. Optuna hyperparameter tuning khi data > 50k rows
9. Walk-forward backtest trước khi scale vốn
10. Thêm Binance API execution (~50 dòng code) khi đủ điều kiện live trade

---

## Giới hạn thực tế

- **~10 ngày data, 1 market regime** (sideways/downtrend) — chưa thấy bull/high-vol
- **SHORT paper_trades n=6 resolved, 3WIN/3LOSS** — CI quá rộng, 50% không có ý nghĩa thống kê
- **Validator SHORT n=28 resolved, precision=42.9%** — có ý nghĩa hơn nhưng vẫn dưới mục tiêu 75%
- **Dead cat bounce** sau liq cascade lớn — 3 LOSS liên tiếp 22-23/05
- **LONG precision thực 7%** — không viable, không trade
- **Sau bỏ liq filter: chưa thấy tăng tín hiệu** — thị trường sideways, liq ≈ 0; cần cascade event
- **Cascade BTC median 0.029% < taker fee 0.10%** — chỉ viable với maker orders
- **TP-hit label chưa đủ data** — 1.5% positive rate cần 50k+ rows
- **SOL: 3 trades, 3 LOSS** — quá sớm, model cần thêm data
