"""
config.py — Single source of truth cho tất cả paths và constants.

Import trong bất kỳ module nào:
    import sys; sys.path.insert(0, str(Path(__file__).parent))
    from config import DATA_DIR, FEATURES_FILE, ...
"""

import os
from pathlib import Path

ROOT_DIR  = Path(__file__).parent
DATA_DIR  = ROOT_DIR / "data"
ML_DIR    = ROOT_DIR / "ml" / "artifacts"

# ── Raw data files (collector → đây) ─────────────────────────────
KLINES_FILE         = DATA_DIR / "klines_1s.csv"
LIQ_FILE            = DATA_DIR / "liquidations.csv"
ORDERBOOK_FILE      = DATA_DIR / "orderbook.csv"
AGGTRADE_FILE       = DATA_DIR / "aggtrades.csv"
SPOT_AGGTRADE_FILE  = DATA_DIR / "spot_aggtrades.csv"
OI_FILE             = DATA_DIR / "open_interest.csv"
FUNDING_FILE        = DATA_DIR / "funding_rate.csv"
BASIS_FILE          = DATA_DIR / "basis.csv"

# ── Processed files (feature_engine / signal → đây) ──────────────
FEATURES_FILE     = DATA_DIR / "features_1m.csv"
PAPER_TRADES_FILE = DATA_DIR / "paper_trades.csv"

# ── ML artifacts ─────────────────────────────────────────────────
META_FILE          = ML_DIR / "meta.json"
TRAIN_HISTORY_FILE = ML_DIR / "train_history.json"

# ── Trading constants (override via .env) ────────────────────────
SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "0.60"))
MIN_RR           = float(os.getenv("MIN_RR",           "1.5"))
MIN_ROWS_TRAIN   = int(os.getenv("MIN_ROWS_TRAIN",     "200"))
HORIZONS         = [1, 2, 3]
RUN_INTERVAL_FE  = 60
