# SESSION SUMMARY — BTC Cascade Liquidation Predictor

## Tổng quan dự án

Hệ thống dự đoán cascade liquidation BTC Futures (Binance) để tìm cơ hội trade.
- **Model:** Ensemble RF+LR+XGB (3 horizons: 1m/2m/3m) × 2 directions (LONG/SHORT) = 6 artifacts
- **Data:** 14,177 rows (2026-05-09 → 2026-05-22, 13 ngày), 1 market regime
- **Pipeline:** 7 services chạy 24/7 trên tmux session `btc`

---

## Trạng thái hệ thống (22/05/2026)

```
tmux session 'btc':
  signal    (win 0)  ✅ Inference mỗi 10s, threshold=0.65, cooldown 900s/direction
  collector (win 1)  ✅ 7 streams Binance (WS + REST)
  features  (win 2)  ✅ Feature engineering mỗi 1 phút, 14,177 rows
  server    (win 3)  ✅ Dashboard http://localhost:8000
  auto_train(win 4)  ✅ Restart sau crash, đang retrain (AUC 0.7185)
  monitor   (win 13) ✅ SHORT monitor terminal
  validator (win 14) ✅ Signal TP/FP tracker

tmux session 'sol':  ✅ SOL pipeline chạy song song (4 windows, 3,660 rows)
```

**Lưu ý:** auto_train đã crash từ nhiều ngày trước (window 10 mất) — đã restart vào window mới.

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

AUC ổn định 0.7185 — model đã hội tụ với data hiện tại (sẽ tăng khi có thêm regime mới).

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

---

## Paper Trading (22/05/2026, 124 total)

| | n | WIN | LOSS | EXPIRED | UNFILLED | Precision | PnL |
|---|---|---|---|---|---|---|---|
| LONG | 91 | 5 (7.1%) | 65 | 21 | 0 | **7.1%** | **-24.88%** |
| SHORT | 33 | 3 (100%) | 0 | 28 | 2 | **100%*** | **+0.35%** |
| **Tổng** | **124** | **8** | **65** | **49** | **2** | — | **-24.53%** |

*SHORT 100% precision chỉ dựa trên n=3 resolved — quá nhỏ để kết luận.

**Phân tích LONG — precision thực sự là 0%:**
- 5 WIN đều xảy ra ngày 15/05, cùng entry=79394.4, cùng prob=0.8188 trong 2 giờ
- Đây là artifact của **feature staleness** (features không update giữa các inference cycle)
- Sau 15/05: **0 WIN** liên tiếp qua 4 ngày (65 LOSS thuần)
- **Kết luận: không nên trade LONG** cho đến khi có bull market data

**Vấn đề fee:**
```
Cascade BTC median move = 0.029% trong 1 phút
Taker fee round-trip    = 0.10%  → không viable
Maker fee round-trip    = 0.02%  → viable (đang dùng USE_MAKER=true)
```

---

## Thay đổi session này (22/05/2026) — cập nhật lần 3

---

### 8. Fix bug timestamp parsing — hệ thống predict trên data cũ ✅ (22/05 ~09:00 UTC)

**Triệu chứng ban đầu:** `read_latest_features()` trả về `2026-05-18 14:45:00` (4 ngày cũ) thay vì timestamp hôm nay.

**Root cause thực sự (2 tầng):**

1. **CSV có mixed timestamp formats:**
   - Rows cũ (trước 2026-05-19): `2026-05-18 14:45:00+00:00` (space separator)
   - Rows mới (từ 2026-05-22): `2026-05-22T08:04:00+00:00` (T separator, ISO 8601)
   - Rows giữa (11779→14188): timestamp RỖNG (artifact từ code cũ, không phục hồi được)

2. **Pandas 2.3.3 behavior:** `pd.to_datetime(series, utc=True, errors="coerce")` **infer format từ phần tử đầu tiên** (space format). Khi gặp T-format → coerce thành NaT. Gọi đơn lẻ thì parse đúng, nhưng gọi trên toàn Series thì fail.

**Fix — thêm `format="ISO8601"` vào tất cả các nơi parse timestamp:**

| File | Line | Fix |
|---|---|---|
| `server/dashboard/data_reader.py` | 69 | `format="ISO8601"` |
| `signal/run.py` | 70 | `format="ISO8601"` |
| `ml/train.py` | 63 | `format="ISO8601"` |
| `ml/auto_train.py` | 63 | `format="ISO8601"` |
| `scripts/monitor_short.py` | 162 | `format="ISO8601"` |
| `scripts/live_predict.py` | 180 | `format="ISO8601"` |
| `scripts/signal_validator.py` | 99, 288 | `format="ISO8601"` |

**Thêm fix `label_builder.py`:**
- Đổi `pd.read_csv(FEATURES_FILE)` → `pd.read_csv(FEATURES_FILE, dtype=str)` để ngăn pandas tự convert types
- Thêm `if pd.isna(t_start): continue` để skip rows có timestamp rỗng

**Kết quả sau fix:**
- `read_latest_features()["timestamp"]` = `2026-05-22T09:00:00Z` ✅
- `GET /api/signal/ → feature_ts: 2026-05-22T08:57:00Z` ✅
- Signal và dashboard predict trên data thật ✅

**Rule đúng cho pandas 2.x:** Luôn dùng `format="ISO8601"` khi đọc timestamp column có thể có mixed formats. Không bao giờ để pandas tự infer format từ Series — nó infer từ phần tử đầu và fail silently cho phần còn lại.

---

### 1. System audit & code review ✅

Kiểm tra toàn bộ hệ thống, tìm bugs thực tế đang ảnh hưởng production.

### 2. Bugs production code đã fix ✅

| File | Bug | Fix |
|---|---|---|
| `server/dashboard/views.py` | `int(request.GET.get(...))` crash `ValueError` nếu param không phải số | Bọc `try/except`, fallback về default |
| `signal/run.py` | Docstring nói `threshold=0.70` nhưng thực tế dùng `SIGNAL_THRESHOLD=0.65` | Sửa docstring |
| `signal/paper_log.py` | `OUTCOME_WINDOW=3min` nhưng docstring + comment nói "30 phút" | Sửa docstring |
| `ml/train.py` | `pd.read_csv(FEATURES_FILE)` không có try/except → crash `EmptyDataError` | Bọc try/except, raise `RuntimeError` |

### 3. Bug nghiêm trọng: auto_train đã chết từ nhiều ngày trước ✅

**Root cause:** `train.py:57` gọi `pd.read_csv()` không có try/except. Khi `features_1m.csv` bị đọc lúc momentarily rỗng (race condition khởi động), toàn bộ auto_train crash và không bao giờ restart.

- Crash xảy ra khi data chỉ có **4,441 rows** (hiện 14,177 rows)
- Pane `btc:10` vẫn còn sống do `; read` trong bash nhưng Python đã chết
- **Fix:** Bọc `pd.read_csv` trong try/except trong `train.py`, restart auto_train

### 4. Test suite hoàn chỉnh — từ 0 → 102 tests pass ✅

**Bugs test infrastructure (tất cả 32 test cũ đều fail):**

| File | Bug | Fix |
|---|---|---|
| — | `tests/generate_fake_data.py` không tồn tại | Tạo mới |
| `test_data_reader.py` | `ROOT_DIR = Path(__file__).parent.parent` = `tests/` (sai, phải là project root) | Sửa thành `.parent.parent.parent` |
| `test_api.py` | ROOT_DIR sai → `SERVER_DIR` trỏ sai → Django `ModuleNotFoundError` | Sửa path |
| Cả 2 files | Patch `dr.OB_FILE` không tồn tại trong `data_reader.py` | Xóa |
| `test_data_reader.py` | Key `liq_zone_upper/lower`, `cvd_5m`, `delta_oi_5m` không tồn tại | Sửa thành key thật |
| `test_api.py` | `/api/signal/` expected `liq_upper`, `liq_lower`, `cvd_5m` | Sửa |
| `test_api.py` | Outcomes chỉ cho phép `WIN/LOSS/""`, bỏ sót `EXPIRED/UNFILLED` | Thêm vào |
| `run_tests.sh` | Path `tests/test_data_reader.py` không tồn tại | Sửa thành `tests/unit/` và `tests/integration/` |

**Tests mới thêm (39 tests):**
- `tests/unit/test_paper_log.py` — 14 tests: `log_signal`, `has_open_trade`, `check_outcomes`, `print_stats`
- `tests/unit/test_predict.py` — 25 tests: config constants, `_build_input`, `predict_cascade_prob`, `predict_cascade_signal`, `predict_time_to_cascade`
- `tests/conftest.py` — Django setup tập trung

**Kết quả:** `71 unit tests + 31 integration tests = 102 passed` ✅

### 5. Performance predict — từ 2.9s → 0.6s (7× speedup) ✅

**Root cause:** Broadcaster gọi 24 model calls/tick thay vì 6 cần thiết (redundant compute).

| | Model calls | Thời gian |
|---|---|---|
| Trước | 24 calls | ~3.9–5.2s/tick |
| Sau | 6 calls | ~580–750ms/tick |

**Thay đổi code:**
- `ml/predict.py`: Thêm `predict_all()` (2 calls: curve_long + curve_short, derive prob/ttc/signal từ đó). Thêm `_build_signal_dict()` helper. `predict_cascade_signal()` refactor thành wrapper 1 dòng.
- `server/dashboard/broadcaster.py`: Xóa `_predict_cascade` + `_predict_signal` + 2 cache riêng. Thay bằng `_get_all_predictions()` → `predict_all()`. Broadcaster cache hit 59/60 ticks (instant), cache miss 1/60 (750ms).

### 6. Fix BTC server warning — `X does not have valid feature names` ✅

**Root cause (2 tầng):**
1. `predict.py:_build_input()` trả `np.ndarray`, `imputer` fit với `pd.DataFrame` → warning mỗi lần predict
2. PID 824155 (server từ May 19) vẫn chạy old code song song với worker mới, cả 2 share cùng terminal pts/5 → warnings "blend" vào output server mới

**Fix:** `_build_input()` trả `pd.DataFrame([row_values], columns=features)`. Kill zombie PID 824155, restart server clean.

### 7. SOL liq_total=0 — điều tra, không phải lỗi ✅

Cả BTC lẫn SOL chỉ có ~16-19% phút có liquidation ≠ 0. SOL max historical = $1.1M (đạt 3 lần trong 3672 rows). Ngưỡng $500k đúng cho cả hai, nhưng thị trường hiện tại quiet.

---

## Phân tích LONG precision — kết luận quan trọng

```
LONG precision thực tế = 0/65 = 0%
  → 5 "wins" ngày 15/05 là artifact feature staleness (cùng entry, cùng prob)
  → Từ 16/05 đến nay: 0 WIN trong 65 LOSS

SHORT precision = 3/3 = 100% (nhưng n=3, quá nhỏ)
  → 28/33 trades SHORT bị EXPIRED (cascade không chạm TP/SL trong 2 phút)
  → 0 LOSS toàn lịch sử — promising nhưng cần thêm n

Nguyên nhân LONG kém:
  1. Market regime: 13 ngày sideways/downtrend — LONG cascade không phát triển
  2. Model chưa thấy bull market data
  3. Threshold không phân biệt được WIN/LOSS (cùng prob ~0.82)
```

---

## Git commits session này

```
2b21aca8  docs: update SESSION_SUMMARY.md to 21/05/2026; fix paper_trades.csv schema
```

*(Session 22/05 chưa commit — các thay đổi: views.py, train.py, paper_log.py, run.py, test suite)*

Push lên cả 2 remote:
- `origin` : git.nsts.com.vn/hoanglongvbhp0703/hoanglongvbhp
- `github` : github.com/hoanglongvbhp0703-sys/btc-liquidation-predictor

---

## Điều kiện để live trade BTC (chưa đạt)

1. ❌ Precision ≥ 75% sustained (SHORT 100% nhưng n=3; LONG thực tế 0%)
2. ❌ 50+ resolved signals ở thr≥0.65 (hiện 68 resolved, nhưng LONG unreliable)
3. ❌ 30+ ngày data, nhiều market regime (hiện 13 ngày, 1 regime)

**Khuyến nghị:** Tạm dừng LONG trading, chỉ theo dõi SHORT cho đến khi có đủ n=30+ resolved.

---

## Việc cần làm theo thứ tự ưu tiên

### 🔴 URGENT — fix ngay (hệ thống đang predict sai data)

1. **Fix features_1m.csv corrupt**: Xem mục "BUG NGHIÊM TRỌNG" ở trên
   ```bash
   # Kiểm tra số cột của rows gần đây
   awk -F',' 'NR>14190 {print NR, NF, $1}' data/features_1m.csv
   # Nếu NF != 57 → đó là nguyên nhân
   ```
2. **Verify fix**: Sau fix, `read_latest_features()["timestamp"]` phải trả về timestamp hôm nay
3. **Restart signal** sau fix

### 🟡 Normal priority

4. **[ĐANG CHẠY]** Tích lũy data — pipeline 24/7, ~1,440 rows/ngày
5. **[CÂN NHẮC]** Tắt LONG signal — precision 0%, đang đốt paper PnL
6. Đánh giá lại SHORT khi đủ 30+ resolved (hiện 3)
7. Xem xét adaptive interval cho auto_train khi data > 50k rows
8. Khi đủ điều kiện: thêm Binance API execution (~50 dòng code)

---

## Giới hạn thực tế

- **13 ngày data, 1 market regime** (sideways/downtrend) — chưa thấy bull/high-vol
- **SHORT n=3 resolved** — CI quá rộng, 100% không có ý nghĩa thống kê
- **LONG precision thực 0%** — 5 wins là artifact, không phải tín hiệu thật
- **Cascade BTC median 0.029% < taker fee 0.10%** — chỉ viable với maker orders
- **auto_train đã chết nhiều ngày** — vừa restart, model artifact từ 21/05 vẫn dùng
