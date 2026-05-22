"""
conftest.py — Pytest configuration cho toàn bộ test suite.

Django setup được thực hiện ở đây để integration tests không cần
tự gọi django.setup() (tránh lỗi "Apps already loaded").
"""

import sys
import os
from pathlib import Path

ROOT_DIR   = Path(__file__).parent.parent
SERVER_DIR = ROOT_DIR / "server"

# Thêm server/ vào sys.path để btc_dashboard và dashboard importable
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "btc_dashboard.settings")
