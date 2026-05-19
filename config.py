"""
config.py — Single source of truth cho tất cả paths và constants.

Import trong bất kỳ module nào:
    import sys; sys.path.insert(0, str(Path(__file__).parent))
    from config import DATA_DIR, FEATURES_FILE, ...

Multi-symbol support (env vars):
    SYMBOL=SOLUSDT DATA_SUBDIR=sol python collector/main.py
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent

# ── Multi-symbol support ──────────────────────────────────────────
SYMBOL      = os.getenv("SYMBOL",      "BTCUSDT")   # futures symbol
SPOT_SYMBOL = os.getenv("SPOT_SYMBOL", SYMBOL)       # spot symbol for basis

_subdir  = os.getenv("DATA_SUBDIR", "")
DATA_DIR = ROOT_DIR / "data" / _subdir if _subdir else ROOT_DIR / "data"
ML_DIR   = ROOT_DIR / "ml" / "artifacts" / _subdir if _subdir else ROOT_DIR / "ml" / "artifacts"

DATA_DIR.mkdir(parents=True, exist_ok=True)
ML_DIR.mkdir(parents=True, exist_ok=True)

# ── Raw data files (collector → đây) ─────────────────────────────
KLINES_FILE          = DATA_DIR / "klines_1s.csv"
LIQ_FILE             = DATA_DIR / "liquidations.csv"
ORDERBOOK_FILE       = DATA_DIR / "orderbook.csv"
AGGTRADE_FILE        = DATA_DIR / "aggtrades.csv"
SPOT_AGGTRADE_FILE   = DATA_DIR / "spot_aggtrades.csv"
OI_FILE              = DATA_DIR / "open_interest.csv"
PREMIUM_INDEX_FILE   = DATA_DIR / "premium_index.csv"   # funding + basis (merged)
FUNDING_FILE         = DATA_DIR / "funding_rate.csv"    # legacy — còn đọc để fallback
BASIS_FILE           = DATA_DIR / "basis.csv"           # legacy — còn đọc để fallback

# ── Processed files (feature_engine / signal → đây) ──────────────
FEATURES_FILE     = DATA_DIR / "features_1m.csv"
PAPER_TRADES_FILE = DATA_DIR / "paper_trades.csv"

# ── ML artifacts ─────────────────────────────────────────────────
META_FILE          = ML_DIR / "meta.json"
TRAIN_HISTORY_FILE = ML_DIR / "train_history.json"

# ── Trading constants (override via .env) ────────────────────────
SIGNAL_THRESHOLD = float(os.getenv("SIGNAL_THRESHOLD", "0.65"))
MIN_RR           = float(os.getenv("MIN_RR",           "1.5"))
MIN_ROWS_TRAIN   = int(os.getenv("MIN_ROWS_TRAIN",     "200"))
HORIZONS         = [1, 2, 3]
RUN_INTERVAL_FE  = 60

# ── Maker order ───────────────────────────────────────────────────
USE_MAKER        = os.getenv("USE_MAKER", "true").lower() == "true"
MAKER_OFFSET_PCT = float(os.getenv("MAKER_OFFSET_PCT", "0.00005"))  # 0.005%
LIQ_FILTER_USD   = float(os.getenv("LIQ_FILTER_USD",   "500000"))   # $500k filter

# ── Signal / trade parameters ─────────────────────────────────────
CASCADE_TP_PCT   = float(os.getenv("CASCADE_TP_PCT",  "0.0012"))   # 0.12% TP
CASCADE_SL_PCT   = float(os.getenv("CASCADE_SL_PCT",  "0.0012"))   # 0.12% SL (1:1 R:R)
SIGNAL_COOLDOWN  = int(os.getenv("SIGNAL_COOLDOWN",   "900"))      # 15 min per direction
MAX_TTC          = float(os.getenv("MAX_TTC",         "2.0"))      # max minutes to cascade
