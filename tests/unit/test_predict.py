"""
test_predict.py — Unit tests cho ml/predict.py (không cần model đã train).

Test các hàm _build_input, predict_cascade_signal logic, config constants.
Không load model thật — dùng mock.
"""

import sys
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "ml"))

import predict as pr
from config import (
    SIGNAL_THRESHOLD, CASCADE_TP_PCT, CASCADE_SL_PCT,
    HORIZONS, USE_MAKER, MAKER_OFFSET_PCT,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

def _fake_feature_row(price=80_000.0) -> dict:
    """Tạo feature row giả với đủ keys cho _build_input."""
    from ml.train import FEATURE_COLS
    row = {col: 0.0 for col in FEATURE_COLS}
    row["current_price"] = price
    row["funding_long_heavy"] = "False"
    row["funding_short_heavy"] = "False"
    row["basis_positive"] = "True"
    return row


def _fake_model_ctx(threshold=0.65) -> dict:
    """Tạo model context giả với mock artifacts."""
    mock_artifact = _make_mock_artifact(prob=0.80)

    long_curves  = {h: mock_artifact for h in HORIZONS}
    short_curves = {h: mock_artifact for h in HORIZONS}

    return {
        "long_curves":  long_curves,
        "short_curves": short_curves,
        "features":     [],
        "threshold":    threshold,
        "meta":         {"avg_auc_test": 0.72, "model_type": "ensemble"},
    }


def _make_mock_artifact(prob: float) -> dict:
    """Tạo artifact mock trả về prob cố định."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = np.array([[1 - prob, prob]])

    mock_imputer = MagicMock()
    mock_imputer.transform.side_effect = lambda x: x

    return {
        "ensemble": {
            "models":       [mock_model],
            "model_names":  ["RF"],
            "imputer":      mock_imputer,
            "scaler":       None,
        }
    }


# ── Tests: config constants ────────────────────────────────────────────────

class TestConfigConstants:
    def test_signal_threshold_in_range(self):
        assert 0.5 <= SIGNAL_THRESHOLD <= 1.0

    def test_tp_sl_positive(self):
        assert CASCADE_TP_PCT > 0
        assert CASCADE_SL_PCT > 0

    def test_tp_sl_reasonable(self):
        """TP/SL phải < 5% (không phải 5 lần)."""
        assert CASCADE_TP_PCT < 0.05
        assert CASCADE_SL_PCT < 0.05

    def test_horizons_sorted(self):
        assert HORIZONS == sorted(HORIZONS)
        assert len(HORIZONS) == 3

    def test_maker_offset_small(self):
        assert 0 <= MAKER_OFFSET_PCT < 0.01


# ── Tests: _build_input ───────────────────────────────────────────────────

class TestBuildInput:
    def test_returns_2d_array(self):
        ctx = _fake_model_ctx()
        ctx["features"] = ["cvd_delta_1m", "funding_rate"]
        row = {"cvd_delta_1m": "100.5", "funding_rate": "0.0001"}
        X = pr._build_input(ctx, row)
        assert X.shape == (1, 2)

    def test_missing_feature_becomes_nan(self):
        ctx = _fake_model_ctx()
        ctx["features"] = ["cvd_delta_1m", "nonexistent_col"]
        row = {"cvd_delta_1m": "50.0"}
        X = pr._build_input(ctx, row)
        assert np.isnan(X[0, 1])

    def test_bool_cols_converted(self):
        ctx = _fake_model_ctx()
        ctx["features"] = ["funding_long_heavy"]
        row = {"funding_long_heavy": "True"}
        X = pr._build_input(ctx, row)
        assert X[0, 0] == 1.0

        row2 = {"funding_long_heavy": "False"}
        X2 = pr._build_input(ctx, row2)
        assert X2[0, 0] == 0.0

    def test_none_val_becomes_nan(self):
        ctx = _fake_model_ctx()
        ctx["features"] = ["some_feature"]
        row = {"some_feature": None}
        X = pr._build_input(ctx, row)
        assert np.isnan(X[0, 0])

    def test_string_float_parsed(self):
        ctx = _fake_model_ctx()
        ctx["features"] = ["price_change_1m"]
        row = {"price_change_1m": "0.0012"}
        X = pr._build_input(ctx, row)
        assert X[0, 0] == pytest.approx(0.0012)


# ── Tests: predict_cascade_prob ───────────────────────────────────────────

class TestPredictCascadeProb:
    def test_returns_float(self):
        ctx = _fake_model_ctx()
        ctx["features"] = []
        row = _fake_feature_row()
        prob = pr.predict_cascade_prob(ctx, row, "long")
        assert isinstance(prob, float)

    def test_prob_in_range(self):
        ctx = _fake_model_ctx()
        ctx["features"] = []
        row = _fake_feature_row()
        prob = pr.predict_cascade_prob(ctx, row, "long")
        assert 0.0 <= prob <= 1.0

    def test_returns_none_if_no_curves(self):
        ctx = _fake_model_ctx()
        ctx["long_curves"] = {}
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_prob(ctx, row, "long")
        assert result is None

    def test_short_direction(self):
        ctx = _fake_model_ctx()
        ctx["features"] = []
        row = _fake_feature_row()
        prob = pr.predict_cascade_prob(ctx, row, "short")
        assert 0.0 <= prob <= 1.0


# ── Tests: predict_cascade_signal ─────────────────────────────────────────

class TestPredictCascadeSignal:
    def test_returns_none_below_threshold(self):
        ctx = _fake_model_ctx(threshold=0.99)  # prob=0.80 < 0.99
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        assert result is None

    def test_returns_signal_above_threshold(self):
        ctx = _fake_model_ctx(threshold=0.50)  # prob=0.80 > 0.50
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        assert result is not None

    def test_signal_has_required_keys(self):
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        assert result is not None
        for key in ("signal", "direction", "prob", "entry", "tp", "sl", "rr", "order_type"):
            assert key in result, f"Thiếu key: {key}"

    def test_long_signal_tp_above_entry(self):
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        if result and result["direction"] == "long":
            assert result["tp"] > result["entry"]
            assert result["sl"] < result["entry"]

    def test_short_signal_tp_below_entry(self):
        # Chỉ SHORT curve có prob cao — disable LONG curves
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["long_curves"]  = {h: _make_mock_artifact(prob=0.30) for h in HORIZONS}
        ctx["short_curves"] = {h: _make_mock_artifact(prob=0.90) for h in HORIZONS}
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        if result and result["direction"] == "short":
            assert result["tp"] < result["entry"]
            assert result["sl"] > result["entry"]

    def test_returns_none_on_zero_price(self):
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 0.0)
        assert result is None

    def test_rr_equals_tp_sl_ratio(self):
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["features"] = []
        row = _fake_feature_row()
        result = pr.predict_cascade_signal(ctx, row, 80_000.0)
        if result:
            expected_rr = round(CASCADE_TP_PCT / CASCADE_SL_PCT, 2)
            assert result["rr"] == pytest.approx(expected_rr)

    def test_maker_offset_applied(self):
        ctx = _fake_model_ctx(threshold=0.50)
        ctx["features"] = []
        row = _fake_feature_row()
        price = 80_000.0
        with patch("predict.USE_MAKER", True), \
             patch("predict.MAKER_OFFSET_PCT", 0.00005):
            result = pr.predict_cascade_signal(ctx, row, price)
        if result and result["direction"] == "long":
            expected_entry = round(price * (1 - 0.00005), 2)
            assert result["entry"] == pytest.approx(expected_entry)


# ── Tests: predict_time_to_cascade ───────────────────────────────────────

class TestPredictTimeToCascade:
    def test_returns_smallest_horizon_above_050(self):
        ctx = _fake_model_ctx()
        # horizon 1m: prob=0.80 (>=0.50) → ttc=1
        ctx["features"] = []
        row = _fake_feature_row()
        ttc = pr.predict_time_to_cascade(ctx, row, "long")
        assert ttc == 1.0

    def test_returns_none_if_all_below_050(self):
        ctx = _fake_model_ctx()
        ctx["long_curves"] = {h: _make_mock_artifact(prob=0.30) for h in HORIZONS}
        ctx["features"] = []
        row = _fake_feature_row()
        ttc = pr.predict_time_to_cascade(ctx, row, "long")
        assert ttc is None
