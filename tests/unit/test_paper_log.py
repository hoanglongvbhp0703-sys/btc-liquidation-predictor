"""
test_paper_log.py — Unit tests cho signal/paper_log.py
"""

import sys
import csv
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

# 'signal' xung đột với Python built-in — load trực tiếp và đăng ký vào sys.modules
import importlib.util as _ilu

def _load_module(reg_name: str, path: Path):
    spec = _ilu.spec_from_file_location(reg_name, path)
    mod  = _ilu.module_from_spec(spec)
    sys.modules[reg_name] = mod   # đăng ký để patch() tìm được
    spec.loader.exec_module(mod)
    return mod

_paper_log = _load_module("paper_log_mod", ROOT_DIR / "signal" / "paper_log.py")

log_signal     = _paper_log.log_signal
check_outcomes = _paper_log.check_outcomes
has_open_trade = _paper_log.has_open_trade
print_stats    = _paper_log.print_stats
PAPER_COLS     = _paper_log.PAPER_COLS
OUTCOME_WINDOW = _paper_log.OUTCOME_WINDOW


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def trades_file(tmp_path):
    return tmp_path / "paper_trades.csv"


@pytest.fixture
def klines_file(tmp_path):
    """Tạo klines_1s.csv tạm với 5 phút data."""
    path = tmp_path / "klines_1s.csv"
    now = datetime.now(tz=timezone.utc)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close",
                    "volume", "taker_buy_vol", "num_trades"])
        for i in range(300):
            ts    = now - timedelta(seconds=300 - i)
            price = 80_000.0 + i * 0.1
            w.writerow([ts.isoformat(),
                        round(price, 2), round(price + 5, 2),
                        round(price - 5, 2), round(price + 1, 2),
                        10.0, 5.0, 100])
    return path


def _make_signal(direction="long", prob=0.80, price=80_000.0):
    from config import CASCADE_TP_PCT, CASCADE_SL_PCT
    if direction == "long":
        entry, tp, sl = price, round(price * (1 + CASCADE_TP_PCT), 2), round(price * (1 - CASCADE_SL_PCT), 2)
        sig = "CASCADE_LONG"
    else:
        entry, tp, sl = price, round(price * (1 - CASCADE_TP_PCT), 2), round(price * (1 + CASCADE_SL_PCT), 2)
        sig = "CASCADE_SHORT"
    return {
        "signal": sig, "direction": direction,
        "prob": prob, "entry": entry, "tp": tp, "sl": sl,
        "rr": 1.0, "est_minutes": 1.0, "order_type": "market",
    }


# ── Tests: log_signal ─────────────────────────────────────────────────────

class TestLogSignal:
    def test_creates_file_with_header(self, trades_file):
        sig = _make_signal()
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
        assert trades_file.exists()
        lines = trades_file.read_text().splitlines()
        assert lines[0].split(",")[0] == "opened_at"

    def test_appends_one_row(self, trades_file):
        import pandas as pd
        sig = _make_signal()
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
        df = pd.read_csv(trades_file)
        assert len(df) == 1

    def test_row_values_correct(self, trades_file):
        import pandas as pd
        sig = _make_signal(direction="short", prob=0.75)
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
        df = pd.read_csv(trades_file)
        row = df.iloc[0]
        assert row["signal"] == "CASCADE_SHORT"
        assert float(row["prob"]) == pytest.approx(0.75)
        assert str(row["outcome"]) in ("", "nan")

    def test_outcome_empty_on_log(self, trades_file):
        import pandas as pd
        sig = _make_signal()
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
        df = pd.read_csv(trades_file, dtype=str, keep_default_na=False)
        assert df.iloc[0]["outcome"] == ""

    def test_all_cols_present(self, trades_file):
        import pandas as pd
        sig = _make_signal()
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
        df = pd.read_csv(trades_file)
        for col in PAPER_COLS:
            assert col in df.columns, f"Thiếu cột: {col}"


# ── Tests: has_open_trade ─────────────────────────────────────────────────

class TestHasOpenTrade:
    def test_no_open_trade_initially(self, trades_file):
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            assert has_open_trade("long") is False

    def test_detects_open_long(self, trades_file):
        sig = _make_signal(direction="long")
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
            assert has_open_trade("long") is True
            assert has_open_trade("short") is False

    def test_closed_trade_not_open(self, trades_file):
        import pandas as pd
        sig = _make_signal(direction="long")
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
            df = pd.read_csv(trades_file, dtype=str, keep_default_na=False)
            df.at[0, "outcome"] = "WIN"
            df.to_csv(trades_file, index=False)
            assert has_open_trade("long") is False


# ── Tests: check_outcomes ─────────────────────────────────────────────────

class TestCheckOutcomes:
    def test_returns_zero_when_empty(self, trades_file, klines_file):
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file), \
             patch.object(_paper_log, "KLINES_FILE", klines_file):
            result = check_outcomes()
        assert result == 0

    def test_pending_trade_not_closed_before_window(self, trades_file, klines_file):
        """Trade vừa mở (< OUTCOME_WINDOW) không bị đóng."""
        sig = _make_signal(direction="long")
        opened_at = datetime.now(tz=timezone.utc)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file), \
             patch.object(_paper_log, "KLINES_FILE", klines_file):
            log_signal(sig, opened_at)
            closed = check_outcomes()
        assert closed == 0

    def test_expired_trade_closed(self, trades_file, klines_file):
        """Trade đã qua OUTCOME_WINDOW → phải được đóng."""
        import pandas as pd
        sig = _make_signal(direction="long", price=80_000.0)
        opened_at = datetime.now(tz=timezone.utc) - OUTCOME_WINDOW - timedelta(seconds=10)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file), \
             patch.object(_paper_log, "KLINES_FILE", klines_file):
            log_signal(sig, opened_at)
            closed = check_outcomes()
        assert closed == 1
        df = pd.read_csv(trades_file, dtype=str, keep_default_na=False)
        assert df.iloc[0]["outcome"] in ("WIN", "LOSS", "EXPIRED", "UNFILLED")

    def test_already_closed_not_recounted(self, trades_file, klines_file):
        """Trade đã có outcome không bị count lại."""
        import pandas as pd
        sig = _make_signal(direction="long")
        opened_at = datetime.now(tz=timezone.utc) - OUTCOME_WINDOW - timedelta(seconds=10)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file), \
             patch.object(_paper_log, "KLINES_FILE", klines_file):
            log_signal(sig, opened_at)
            check_outcomes()        # đóng lần 1
            closed2 = check_outcomes()   # không nên đóng thêm
        assert closed2 == 0


# ── Tests: print_stats ────────────────────────────────────────────────────

class TestPrintStats:
    def test_no_crash_empty_file(self, trades_file, capsys):
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            print_stats()
        out = capsys.readouterr().out
        assert "Paper Trading Stats" in out

    def test_shows_win_count(self, trades_file, capsys):
        import pandas as pd
        sig = _make_signal(direction="long")
        opened_at = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        with patch.object(_paper_log, "PAPER_TRADES_FILE", trades_file):
            log_signal(sig, opened_at)
            df = pd.read_csv(trades_file, dtype=str, keep_default_na=False)
            df.at[0, "outcome"] = "WIN"
            df.at[0, "pnl_pct"] = "0.12"
            df.to_csv(trades_file, index=False)
            print_stats()
        out = capsys.readouterr().out
        assert "WIN" in out
