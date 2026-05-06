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
PYTEST="$VENV/bin/pytest"

# Cài pytest nếu thiếu
if ! "$PYTHON" -m pytest --version &>/dev/null; then
    echo "[setup] Installing pytest..."
    "$PYTHON" -m pip install pytest --quiet
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " BTC Dashboard — Test Suite"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "▶ Step 1: Generate fake data"
"$PYTHON" tests/generate_fake_data.py
echo ""

echo "▶ Step 2: Run tests"
"$PYTHON" -m pytest tests/test_data_reader.py tests/test_api.py \
    --tb=short \
    -q \
    "$@"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Done"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
