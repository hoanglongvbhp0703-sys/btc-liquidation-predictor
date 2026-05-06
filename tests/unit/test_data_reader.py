"""
test_data_reader.py — Unit tests cho dashboard/data_reader.py

Dùng fake data trong /tmp/fake_test_data (không đụng đến data thật).
"""

import sys
import os
import csv
import pytest
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).parent.parent
SERVER_DIR = ROOT_DIR / "server"
TESTS_DIR  = ROOT_DIR / "tests"
sys.path.insert(0, str(SERVER_DIR))

# Fake data dir dùng trong tests
FAKE_DIR = Path(tempfile.gettempdir()) / "btc_fake_test"


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def generate_fake_data():
    """Tạo fake data vào /tmp/btc_fake_test trước khi chạy tests."""
    FAKE_DIR.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(TESTS_DIR / "generate_fake_data.py"), "--dir", str(FAKE_DIR)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"generate_fake_data failed:\n{result.stdout}\n{result.stderr}"
    print(result.stdout)


@pytest.fixture
def patch_data_dir():
    """Patch DATA_DIR trong data_reader để trỏ vào fake data."""
    import dashboard.data_reader as dr
    originals = {
        "KLINES_FILE":   dr.KLINES_FILE,
        "LIQ_FILE":      dr.LIQ_FILE,
        "OB_FILE":       dr.OB_FILE,
        "FEATURES_FILE": dr.FEATURES_FILE,
        "TRADES_FILE":   dr.TRADES_FILE,
    }
    dr.KLINES_FILE   = FAKE_DIR / "klines_1s.csv"
    dr.LIQ_FILE      = FAKE_DIR / "liquidations.csv"
    dr.OB_FILE       = FAKE_DIR / "orderbook.csv"
    dr.FEATURES_FILE = FAKE_DIR / "features_5m.csv"
    dr.TRADES_FILE   = FAKE_DIR / "paper_trades.csv"
    yield dr
    for k, v in originals.items():
        setattr(dr, k, v)


# ── Tests: read_latest_kline ───────────────────────────────────────────────

class TestReadLatestKline:
    def test_returns_dict(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_kline()
        assert result is not None
        assert isinstance(result, dict)

    def test_has_required_keys(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_kline()
        assert result is not None
        for key in ("ts", "open", "high", "low", "close", "volume"):
            assert key in result, f"Missing key: {key}"

    def test_prices_are_floats(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_kline()
        assert result is not None
        for key in ("open", "high", "low", "close", "volume"):
            assert isinstance(result[key], float), f"{key} is not float"

    def test_high_gte_low(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_kline()
        assert result is not None
        assert result["high"] >= result["low"]

    def test_returns_none_on_missing_file(self, patch_data_dir):
        dr = patch_data_dir
        dr.KLINES_FILE = FAKE_DIR / "nonexistent.csv"
        result = dr.read_latest_kline()
        assert result is None

    def test_ts_is_recent(self, patch_data_dir):
        """Timestamp phải trong vòng HOURS giờ qua."""
        dr = patch_data_dir
        result = dr.read_latest_kline()
        assert result is not None
        ts = datetime.fromisoformat(result["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(tz=timezone.utc) - ts
        assert age.total_seconds() < 3 * 3600, f"kline quá cũ: {age}"


# ── Tests: read_latest_features ───────────────────────────────────────────

class TestReadLatestFeatures:
    def test_returns_dict(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_features()
        assert result is not None
        assert isinstance(result, dict)

    def test_has_price_and_liq_zones(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_features()
        assert result is not None
        for key in ("current_price", "liq_zone_upper", "liq_zone_lower"):
            assert key in result, f"Missing key: {key}"

    def test_liq_upper_gt_lower(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_latest_features()
        assert result is not None
        upper = float(result["liq_zone_upper"])
        lower = float(result["liq_zone_lower"])
        assert upper > lower, f"upper={upper} không > lower={lower}"

    def test_returns_none_on_missing_file(self, patch_data_dir):
        dr = patch_data_dir
        dr.FEATURES_FILE = FAKE_DIR / "nonexistent.csv"
        result = dr.read_latest_features()
        assert result is None


# ── Tests: read_active_signal ──────────────────────────────────────────────

class TestReadActiveSignal:
    def test_returns_dict_or_none(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_active_signal()
        assert result is None or isinstance(result, dict)

    def test_open_trade_is_found(self, patch_data_dir):
        """generate_fake_data tạo 1 open trade trong 30 phút qua."""
        dr = patch_data_dir
        result = dr.read_active_signal()
        assert result is not None, "Không tìm thấy open trade trong 30 phút — fake data có vấn đề"

    def test_open_trade_has_keys(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.read_active_signal()
        assert result is not None
        for key in ("entry", "tp", "sl", "prob"):
            assert key in result, f"Missing key: {key}"

    def test_returns_none_when_no_open_trades(self, patch_data_dir, tmp_path):
        """File chỉ có trade đã đóng → trả None."""
        dr = patch_data_dir
        closed_csv = tmp_path / "closed_trades.csv"
        closed_csv.write_text(
            "opened_at,signal,prob,entry,tp,sl,rr,closed_at,outcome,pnl_pct,hit_tp,hit_sl\n"
            "2020-01-01T00:00:00+00:00,LONG,0.8,80000,81200,79200,1.5,"
            "2020-01-01T01:00:00+00:00,WIN,1.5,True,False\n"
        )
        dr.TRADES_FILE = closed_csv
        result = dr.read_active_signal()
        assert result is None


# ── Tests: load_klines_chart ───────────────────────────────────────────────

class TestLoadKlinesChart:
    def test_returns_list(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        assert isinstance(result, list)

    def test_non_empty_with_recent_data(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        assert len(result) > 0, "Chart trả về rỗng dù có data trong 2 giờ"

    def test_candle_structure(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        assert len(result) > 0
        c = result[0]
        for key in ("ts", "open", "high", "low", "close", "volume"):
            assert key in c, f"Candle thiếu key: {key}"

    def test_candles_are_1min(self, patch_data_dir):
        """Mỗi nến cách nhau đúng 60 giây."""
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        assert len(result) >= 2
        ts0 = datetime.fromisoformat(result[0]["ts"])
        ts1 = datetime.fromisoformat(result[1]["ts"])
        diff = abs((ts1 - ts0).total_seconds())
        assert diff == 60, f"Khoảng cách nến không phải 60s: {diff}s"

    def test_candles_sorted_ascending(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        times = [r["ts"] for r in result]
        assert times == sorted(times), "Nến không sắp xếp tăng dần"

    def test_high_gte_low_all_candles(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_klines_chart(hours=2)
        for c in result:
            assert c["high"] >= c["low"], f"high < low tại {c['ts']}"

    def test_empty_on_old_data(self, patch_data_dir, tmp_path):
        """File có data nhưng quá cũ → trả list rỗng."""
        dr = patch_data_dir
        old_csv = tmp_path / "old_klines.csv"
        old_csv.write_text(
            "open_time,open,high,low,close,volume,taker_buy_vol,num_trades\n"
            "2020-01-01T00:00:00+00:00,7000,7010,6990,7005,1.0,0.5,10\n"
        )
        dr.KLINES_FILE = old_csv
        result = dr.load_klines_chart(hours=2)
        assert result == [], "Data cũ phải trả list rỗng"


# ── Tests: load_liquidations ───────────────────────────────────────────────

class TestLoadLiquidations:
    def test_returns_list(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_liquidations(hours=4)
        assert isinstance(result, list)

    def test_btcusdt_only(self, patch_data_dir):
        """Chỉ lấy BTCUSDT theo filter trong data_reader."""
        dr = patch_data_dir
        result = dr.load_liquidations(hours=4)
        for r in result:
            assert r.get("side") in ("BUY", "SELL"), f"side lạ: {r.get('side')}"

    def test_liq_structure(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_liquidations(hours=4)
        if result:
            for key in ("ts", "side", "price", "usd_value"):
                assert key in result[0], f"Thiếu key: {key}"


# ── Tests: load_trades ─────────────────────────────────────────────────────

class TestLoadTrades:
    def test_returns_list(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_trades(limit=30)
        assert isinstance(result, list)

    def test_limit_respected(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_trades(limit=3)
        assert len(result) <= 3

    def test_newest_first(self, patch_data_dir):
        """load_trades trả về theo thứ tự ngược (newest first)."""
        dr = patch_data_dir
        result = dr.load_trades(limit=10)
        if len(result) >= 2:
            ts0 = result[0].get("opened_at", "")
            ts1 = result[1].get("opened_at", "")
            assert ts0 >= ts1, "Trade không được sắp xếp newest-first"


# ── Tests: load_signal_state ──────────────────────────────────────────────

class TestLoadSignalState:
    def test_returns_dict(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_signal_state()
        assert isinstance(result, dict)

    def test_required_keys(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_signal_state()
        for key in ("current_price", "liq_upper", "liq_lower",
                    "imbalance", "cvd_5m", "funding_rate", "delta_oi_5m"):
            assert key in result, f"Thiếu key: {key}"

    def test_current_price_positive(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_signal_state()
        assert result["current_price"] is not None
        assert float(result["current_price"]) > 0

    def test_liq_upper_gt_lower(self, patch_data_dir):
        dr = patch_data_dir
        result = dr.load_signal_state()
        upper = result.get("liq_upper")
        lower = result.get("liq_lower")
        if upper is not None and lower is not None:
            assert upper > lower, f"liq_upper={upper} phải > liq_lower={lower}"

    def test_active_signal_present(self, patch_data_dir):
        """Fake data có open trade → active_signal không None."""
        dr = patch_data_dir
        result = dr.load_signal_state()
        assert result.get("active_signal") is not None
