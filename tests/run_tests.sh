#!/bin/bash
# run_tests.sh — Chạy toàn bộ test suite
# Usage:
#   ./tests/run_tests.sh           # chạy tất cả
#   ./tests/run_tests.sh -v        # verbose
#   ./tests/run_tests.sh -k "kline" # chỉ test có chữ "kline"

set -e
cd "$(dirname "$0")/.."

VENV=".venv"
PYTHON="$VENV/bin/python"

# Cài pytest nếu thiếu
if ! "$PYTHON" -m pytest --version &>/dev/null; then
    echo "[setup] Installing pytest..."
    "$PYTHON" -m pip install pytest pytest-django --quiet
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " BTC Dashboard — Test Suite"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "▶ Step 1: Generate fake data"
"$PYTHON" tests/generate_fake_data.py
echo ""

echo "▶ Step 2: Run unit tests"
"$PYTHON" -m pytest tests/unit/ --tb=short -q "$@"
echo ""

echo "▶ Step 3: Run integration tests"
"$PYTHON" -m pytest tests/integration/ --tb=short -q "$@"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Done"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
