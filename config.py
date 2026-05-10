"""
config.py — Single source of truth cho tất cả paths và constants.

Import trong bất kỳ module nào:
    import sys; sys.path.insert(0, str(Path(__file__).parent))
    from config import DATA_DIR, FEATURES_FILE, ...
"""

from pathlib import Path

ROOT_DIR  = Path(__file__).parent
DATA_DIR  = ROOT_DIR / "data"
ML_DIR    = ROOT_DIR / "ml" / "artifacts"

# ── Raw data files (collector → đây) ─────────────────────────────
KLINES_FILE    = DATA_DIR / "klines_1s.csv"
LIQ_FILE       = DATA_DIR / "liquidations.csv"
ORDERBOOK_FILE = DATA_DIR / "orderbook.csv"
AGGTRADE_FILE  = DATA_DIR / "aggtrades.csv"
OI_FILE        = DATA_DIR / "open_interest.csv"
FUNDING_FILE   = DATA_DIR / "funding_rate.csv"

# ── Processed files (feature_engine / signal → đây) ──────────────
FEATURES_FILE   = DATA_DIR / "features_5m.csv"
PAPER_TRADES_FILE = DATA_DIR / "paper_trades.csv"

# ── ML artifacts ─────────────────────────────────────────────────
MODEL_LONG_FILE    = ML_DIR / "lgb_model_long.pkl"
MODEL_SHORT_FILE   = ML_DIR / "lgb_model_short.pkl"
META_FILE          = ML_DIR / "meta.json"
TRAIN_HISTORY_FILE = ML_DIR / "train_history.json"

# ── Trading constants ─────────────────────────────────────────────
SIGNAL_THRESHOLD = 0.70
MIN_RR           = 1.5
HORIZONS         = [5, 10, 15, 20, 25, 30]
MIN_ROWS_TRAIN   = 200
