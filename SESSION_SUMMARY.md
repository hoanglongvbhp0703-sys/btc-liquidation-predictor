# SESSION SUMMARY — BTC Cascade Liquidation Predictor

## Tổng quan dự án

Hệ thống dự đoán cascade liquidation BTC Futures (Binance) để tìm cơ hội trade.
- **Model:** Ensemble RF+LR+XGB (3 horizons: 1m/2m/3m) × 2 directions (LONG/SHORT) = 6 artifacts + 6 TP-hit artifacts
- **Data:** 14,740 rows (2026-05-09 → 2026-05-23, 14 ngày), 1 market regime
- **Pipeline:** 7 services BTC + 4 services SOL chạy 24/7

---

## Trạng thái hệ thống (23/05/2026 ~10:35 UTC)

```
tmux session 'btc':
  signal    (win 0)  ✅ Predict mỗi 10s — KHÔNG còn liq filter, model tự quyết
  collector (win 1)  ✅ 7 streams Binance (WS + REST)
  features  (win 2)  ✅ Feature engineering mỗi 1 phút, 14,740 rows
  server    (win 3)  ✅ Dashboard http://localhost:8000
  auto_train(win 4)  ✅ Retrain mỗi 60 phút, avg AUC=0.700
  monitor   (win 5)  ✅ Running (stat lịch sử: precision=90.8%, recall=43.5%)
  validator (win 6)  ⚠️ Running nhưng frozen ở data 18/05 — không track trades mới

tmux session 'sol':  ✅ SOL pipeline (4 windows, 5,213 rows, AUC=0.667)
```

---

## Model hiện tại (retrain 23/05 ~10:34 UTC, 14,740 rows)

| Target | CASCADE AUC | TP-hit AUC | CASCADE prec@0.65 |
|---|---|---|---|
| short_1m | **0.758** | 0.660 | 50% (n=22) |
| short_2m | **0.704** | 0.631 | 52% (n=27) |
| short_3m | 0.674 | 0.617 | 48% (n=27) |
| long_1m  | **0.770** | 0.738 | 50% (n=16) |
| long_2m  | 0.652 | 0.652 | 44% (n=16) |
| long_3m  | 0.644 | 0.624 | 43% (n=7)  |
| **Avg**  | **0.700** | 0.654 | — |

AUC vừa vượt ngưỡng 0.70 lần đầu (0.696 → 0.698 → 0.700).
TP-hit model AUC thấp hơn CASCADE vì positive class hiếm hơn (1.5–3.8% vs 6.7%) và 14k rows chưa đủ.

---

## Config hiện tại (single source of truth: config.py)

| Parameter | Giá trị | Override |
|---|---|---|
| `SIGNAL_THRESHOLD` | **0.65** | env var |
| `CASCADE_TP_PCT` | **0.120%** | env var |
| `CASCADE_SL_PCT` | **0.120%** | env var |
| `SIGNAL_COOLDOWN` | **900s (15min)** | env var |
| `MAX_TTC` | **2.0m** | env var |
| ~~`LIQ_FILTER_USD`~~ | ~~$500,000~~ | **ĐÃ XOÁ 23/05** |
| `USE_MAKER` | **true** | env var |
| `MAKER_OFFSET_PCT` | **0.005%** | env var |

---

## Paper Trading (23/05/2026 ~10:35 UTC)

| | n | WIN | LOSS | EXPIRED | UNFILLED | Precision (resolved) | PnL |
|---|---|---|---|---|---|---|---|
| LONG  | 91 | 5 | 65 | 21 | 0 | **7%** (n=70) | **-24.88%** |
| SHORT | 36 | 3 | 3  | 28 | 2 | **50%** (n=6) | **-0.01%** |
| **Tổng** | **127** | **8** | **68** | **49** | **2** | — | **-24.89%** |

**Phân tích SHORT — pattern 3 LOSS liên tiếp (22–23/05):**
- 3 WIN đều ngày 18/05, prob 0.62–0.82
- 3 LOSS: 22/05 18:46 (prob=0.856, liq=$8M), 22/05 19:31 (prob=0.781, liq=$11.5M), 23/05 07:51 (prob=0.716)
- Pattern: liq LONG cascade lớn → giá drop → model fire SHORT → **dead cat bounce** → hit SL
- Precision giảm 100% (n=3) → 50% (n=6) — cần thêm n để kết luận

**Phân tích recall hệ thống (phát hiện ngày 23/05):**
- Tổng cascade SHORT trong 14 ngày: **987 events**
- Hệ thống bắt được: **36 trades = 3.6% recall** (do liq filter cũ chặn 97.5%)
- Sau khi bỏ liq filter: kỳ vọng tăng lên ~40–52 signal/ngày

**Precision trên CASCADE label (out-of-sample test set):**
- Với liq filter (cũ): 75.2% — nhưng chỉ 8 signal/ngày
- Không có liq filter: 44.4% (out-of-sample) — nhưng 52 signal/ngày
- Monitor (90.8%) là in-sample và không có liq filter → không so sánh trực tiếp được

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
- Liq filter làm precision giảm: 86.5% (no filter) → 75.2% (có filter), với ít signal hơn 6×

| Phương án | Signal/ngày | Precision (cascade label, out-of-sample) |
|---|---|---|
| Liq>=500k + prob>=0.65 (cũ) | ~8 | 75.2% |
| Prob>=0.65 only (mới) | ~52 | 86.5% (in-sample) / 44.4% (out-of-sample) |
| Prob>=0.70 only | ~41 | 92.3% (in-sample) |

---

### 13. Xoá LIQ_FILTER_USD ✅ (23/05)

**Thay đổi:**
- `config.py`: Xoá constant `LIQ_FILTER_USD`
- `signal/run.py`: Xoá import + block liq filter (4 dòng) + cập nhật docstring
- Restart cả BTC (btc:0) và SOL (sol:2) signal services

**Kết quả:** Signal không còn bị block bởi liq filter. Model tự quyết dựa vào prob >= 0.65.
Kỳ vọng đủ n=50 resolved SHORT trong 1–2 tuần thay vì vài tháng.

---

### 14. Thêm TP-hit labels + train models ✅ (23/05)

**Motivation:** CASCADE label đo "liq event xảy ra" (proxy), TP-hit label đo "giá chạm TP 0.12% trong Xm" (thực tế hơn).

**Thay đổi code:**
- `feature_engine/label_builder.py`:
  - Thêm `build_tp_labels()` — vectorized, tính `tp_hit_short_Xm` / `tp_hit_long_Xm` từ `current_price`
  - Gọi từ `build_pending_labels()` sau mỗi lần label cascade
- `ml/train.py`:
  - Train thêm 6 TP-hit models nếu columns tồn tại
  - In so sánh CASCADE vs TP-hit AUC
  - Lưu `avg_tp_auc_test` vào meta.json

**Kết quả:** TP-hit models AUC thấp hơn CASCADE (0.654 vs 0.700). Nguyên nhân:
- Positive class quá hiếm: tp_hit_short_1m chỉ 1.52%, tp_hit_short_2m chỉ 3.78%
- Close price 1m là xấp xỉ thô — bỏ qua intra-minute move → false negatives
- 14k rows chưa đủ để học pattern này

**Quyết định:** Giữ CASCADE models cho production. TP-hit models lưu sẵn tại `ml/artifacts/ens_tp_hit_*.pkl` để dùng lại khi đủ 50k+ rows.

**⚠️ Bugs chưa fix trong code mới này — cần làm tiếp:**
- `build_tp_labels()` recompute ALL 14k rows mỗi phút → tốn CPU không cần thiết
- `build_pending_labels()` ghi CSV 2 lần/phút (1 lần cascade, 1 lần TP) → double write
- Nên: chỉ compute TP labels cho các rows mới (chưa có label), ghi 1 lần duy nhất

---

## Git commits

```
a5176074  fix: timestamp parsing, CVD chart history, test suite, performance (22/05/2026)
2b21aca8  docs: update SESSION_SUMMARY.md to 21/05/2026; fix paper_trades.csv schema
ff9c7005  docs: update SESSION_SUMMARY.md to 20/05/2026
7565ca10  fix: correct UI bugs — hardcoded TP/SL labels, CVD chart, SYMBOL filter, ML_DIR
1a74ad6d  refactor: eliminate hardcodes and unused files, add SOL pipeline
5db45f65  feat: switch production model to Ensemble RF+LR+XGB
```

*(Chưa commit thay đổi ngày 23/05)*

---

## Điều kiện để live trade BTC (chưa đạt)

1. ❌ Precision ≥ 75% sustained — SHORT 50% (n=6); LONG thực tế 7% (n=70)
2. ❌ 50+ resolved SHORT signals — hiện 6 resolved
3. ❌ 30+ ngày data, nhiều market regime — hiện 14 ngày, 1 regime (sideways/downtrend)

**Khuyến nghị:** Không trade LONG. Theo dõi SHORT khi đủ n=30+ resolved.
Sau khi bỏ liq filter, kỳ vọng đủ n=50 trong 1–2 tuần.

---

## Việc cần làm

### 🔴 Cần làm ngay (bugs code mới)

1. **Fix double write trong label_builder.py** — `build_pending_labels()` đang ghi CSV 2 lần/phút:
   - Gọi `build_tp_labels(df_feat)` TRƯỚC `df_feat.to_csv()`, không phải sau
   - `build_tp_labels()` không nên ghi CSV khi được gọi với df_feat argument (chỉ update in-memory)

2. **Fix recompute toàn bộ trong build_tp_labels()** — chỉ tính cho rows chưa có TP label:
   - Kiểm tra `df_feat[col_s].isna()` → chỉ compute rows NaN
   - Hoặc: chỉ compute 10 rows cuối (rows mới + rows vừa có đủ future data)

### 🟡 Normal priority

3. **[ĐANG CHẠY]** Tích lũy resolved paper trades — mục tiêu n=50 SHORT resolved
4. Đánh giá lại SHORT precision khi đủ n=30 resolved
5. Fix validator (btc:6) — hiện frozen ở data 18/05, không track trades mới
6. Xem xét raise SIGNAL_THRESHOLD lên 0.70 nếu SHORT precision tiếp tục ≤ 50%
7. Khi đủ điều kiện: thêm Binance API execution (~50 dòng code)

### 🔵 Cải thiện dài hạn

8. Khi đủ 50k+ rows: retrain TP-hit models với klines_1s (chính xác hơn close price 1m)
9. Bull market data sẽ cải thiện LONG AUC — chờ regime thay đổi
10. SOL cần thêm ~10k rows trước khi model có ý nghĩa (hiện 5,213 rows)
11. Optuna hyperparameter tuning khi data > 50k rows
12. Walk-forward backtest trước khi scale vốn

---

## Giới hạn thực tế

- **14 ngày data, 1 market regime** (sideways/downtrend) — chưa thấy bull/high-vol
- **SHORT n=6 resolved, 3 WIN / 3 LOSS** — CI quá rộng, 50% không có ý nghĩa thống kê
- **Dead cat bounce** sau liq cascade lớn — 3 LOSS liên tiếp 22–23/05, đều prob cao (0.72–0.86)
- **LONG precision thực 7%** — 5 wins là artifact feature staleness, không phải tín hiệu thật
- **Recall cực thấp** — hệ thống (cũ) chỉ bắt 3.6% cascade thực sự do liq filter
- **Cascade BTC median 0.029% < taker fee 0.10%** — chỉ viable với maker orders
- **TP-hit label chưa đủ data** — 1.5% positive rate cần 50k+ rows để train hiệu quả
- **SOL: 3 trades, 3 LOSS** — quá sớm, model cần thêm data
