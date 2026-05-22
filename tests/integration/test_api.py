"""
test_api.py — Integration tests cho Django REST API.

Dùng Django test client (không cần server đang chạy).
Patch DATA_DIR để dùng fake data thay vì data thật.
"""

import sys
import os
import subprocess
import tempfile
import pytest
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR   = Path(__file__).parent.parent.parent   # tests/integration/../../ = project root
SERVER_DIR = ROOT_DIR / "server"
TESTS_DIR  = ROOT_DIR / "tests"

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "btc_dashboard.settings")
sys.path.insert(0, str(SERVER_DIR))

import django
django.setup()

from django.test import Client

FAKE_DIR = Path(tempfile.gettempdir()) / "btc_fake_test"


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def generate_fake_data():
    FAKE_DIR.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(TESTS_DIR / "generate_fake_data.py"), "--dir", str(FAKE_DIR)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"generate_fake_data failed:\n{result.stdout}\n{result.stderr}"


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def patch_data_files():
    """Patch tất cả file paths trong data_reader trỏ vào fake data."""
    import dashboard.data_reader as dr
    originals = {
        "KLINES_FILE":   dr.KLINES_FILE,
        "LIQ_FILE":      dr.LIQ_FILE,
        "FEATURES_FILE": dr.FEATURES_FILE,
        "TRADES_FILE":   dr.TRADES_FILE,
    }
    dr.KLINES_FILE   = FAKE_DIR / "klines_1s.csv"
    dr.LIQ_FILE      = FAKE_DIR / "liquidations.csv"
    dr.FEATURES_FILE = FAKE_DIR / "features_5m.csv"
    dr.TRADES_FILE   = FAKE_DIR / "paper_trades.csv"
    yield
    for k, v in originals.items():
        setattr(dr, k, v)


# ── GET /api/klines/ ───────────────────────────────────────────────────────

class TestApiKlines:
    def test_status_200(self, client):
        res = client.get("/api/klines/")
        assert res.status_code == 200

    def test_returns_json_list(self, client):
        res = client.get("/api/klines/")
        data = res.json()
        assert isinstance(data, list)

    def test_non_empty(self, client):
        res = client.get("/api/klines/")
        data = res.json()
        assert len(data) > 0, "API trả list rỗng dù có fake data"

    def test_candle_keys(self, client):
        res = client.get("/api/klines/")
        data = res.json()
        assert len(data) > 0
        candle = data[0]
        for key in ("ts", "open", "high", "low", "close", "volume"):
            assert key in candle, f"Candle thiếu key: {key}"

    def test_hours_param(self, client):
        res1 = client.get("/api/klines/?hours=1")
        res2 = client.get("/api/klines/?hours=2")
        d1, d2 = res1.json(), res2.json()
        assert len(d2) >= len(d1), "hours=2 phải có nhiều nến hơn hours=1"

    def test_hours_invalid_returns_200(self, client):
        """hours không hợp lệ phải trả 200 (không crash)."""
        res = client.get("/api/klines/?hours=abc")
        assert res.status_code == 200

    def test_candles_sorted(self, client):
        res = client.get("/api/klines/")
        data = res.json()
        times = [r["ts"] for r in data]
        assert times == sorted(times)

    def test_prices_sensible(self, client):
        """Giá phải > 0 và không có NaN/null."""
        res = client.get("/api/klines/")
        data = res.json()
        for c in data:
            for key in ("open", "high", "low", "close"):
                assert c[key] is not None
                assert c[key] > 0


# ── GET /api/signal/ ───────────────────────────────────────────────────────

class TestApiSignal:
    def test_status_200(self, client):
        res = client.get("/api/signal/")
        assert res.status_code == 200

    def test_returns_json_object(self, client):
        res = client.get("/api/signal/")
        data = res.json()
        assert isinstance(data, dict)

    def test_required_keys(self, client):
        """Kiểm tra keys thực sự được trả về bởi load_signal_state()."""
        res = client.get("/api/signal/")
        data = res.json()
        for key in ("current_price", "imbalance", "cvd_1m",
                    "funding_rate", "delta_oi_1m"):
            assert key in data, f"Thiếu key: {key}"

    def test_no_nan_in_response(self, client):
        """_sanitize() trong views.py phải convert NaN → null."""
        res = client.get("/api/signal/")
        raw = res.content.decode()
        assert "NaN" not in raw, "Response chứa NaN không hợp lệ"
        assert "Infinity" not in raw

    def test_current_price_positive(self, client):
        res = client.get("/api/signal/")
        data = res.json()
        assert data["current_price"] is not None
        assert data["current_price"] > 0

    def test_active_signal_has_entry(self, client):
        """Fake data có open trade → active_signal phải có entry."""
        res = client.get("/api/signal/")
        data = res.json()
        sig = data.get("active_signal")
        assert sig is not None
        assert "entry" in sig
        assert sig["entry"] > 0


# ── GET /api/trades/ ───────────────────────────────────────────────────────

class TestApiTrades:
    def test_status_200(self, client):
        res = client.get("/api/trades/")
        assert res.status_code == 200

    def test_returns_json_list(self, client):
        res = client.get("/api/trades/")
        data = res.json()
        assert isinstance(data, list)

    def test_non_empty(self, client):
        res = client.get("/api/trades/")
        data = res.json()
        assert len(data) > 0

    def test_trade_keys(self, client):
        res = client.get("/api/trades/")
        data = res.json()
        trade = data[0]
        for key in ("opened_at", "signal", "prob", "entry", "tp", "sl", "outcome"):
            assert key in trade, f"Trade thiếu key: {key}"

    def test_limit_param(self, client):
        res = client.get("/api/trades/?limit=2")
        data = res.json()
        assert len(data) <= 2

    def test_limit_invalid_returns_200(self, client):
        """limit không hợp lệ phải trả 200 (không crash)."""
        res = client.get("/api/trades/?limit=abc")
        assert res.status_code == 200

    def test_outcomes_valid(self, client):
        """outcome hợp lệ: WIN, LOSS, EXPIRED, UNFILLED, hoặc rỗng (open)."""
        res = client.get("/api/trades/")
        data = res.json()
        valid = {"WIN", "LOSS", "EXPIRED", "UNFILLED", ""}
        for t in data:
            assert t["outcome"] in valid, f"outcome lạ: {t['outcome']}"


# ── GET /api/liq/ ──────────────────────────────────────────────────────────

class TestApiLiq:
    def test_status_200(self, client):
        res = client.get("/api/liq/")
        assert res.status_code == 200

    def test_returns_json_list(self, client):
        res = client.get("/api/liq/")
        data = res.json()
        assert isinstance(data, list)

    def test_liq_structure(self, client):
        res = client.get("/api/liq/")
        data = res.json()
        if data:
            for key in ("ts", "side", "price", "usd_value"):
                assert key in data[0], f"Thiếu key: {key}"

    def test_side_is_buy_or_sell(self, client):
        res = client.get("/api/liq/")
        data = res.json()
        for liq in data:
            assert liq["side"] in ("BUY", "SELL")

    def test_hours_param(self, client):
        res = client.get("/api/liq/?hours=1")
        assert res.status_code == 200

    def test_hours_invalid_returns_200(self, client):
        """hours không hợp lệ phải trả 200 (không crash)."""
        res = client.get("/api/liq/?hours=abc")
        assert res.status_code == 200

    def test_prices_positive(self, client):
        res = client.get("/api/liq/")
        data = res.json()
        for liq in data:
            assert liq["price"] > 0
            assert liq["usd_value"] >= 0


# ── GET / (dashboard page) ─────────────────────────────────────────────────

class TestDashboardPage:
    def test_status_200(self, client):
        res = client.get("/")
        assert res.status_code == 200

    def test_html_content(self, client):
        res = client.get("/")
        assert b"<html" in res.content.lower() or b"<!doctype" in res.content.lower()

    def test_contains_chart_element(self, client):
        res = client.get("/")
        assert b"chart" in res.content.lower()
