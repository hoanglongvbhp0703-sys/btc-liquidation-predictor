# ══════════════════════════════════════════════════════════════════
#  BTC Liquidation Predictor — Makefile
#  Usage: make <target>
# ══════════════════════════════════════════════════════════════════

PYTHON  := .venv/bin/python
PIP     := .venv/bin/pip
MANAGE  := $(PYTHON) server/manage.py

.PHONY: help setup venv install train server \
        collector features signal \
        docker-up docker-down docker-logs docker-build \
        test lint clean

# ── Default ──────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  BTC Liquidation Predictor"
	@echo "  ─────────────────────────────────────────────"
	@echo "  make setup        Bootstrap toàn bộ project"
	@echo "  make venv         Tạo virtual environment"
	@echo "  make install      Cài tất cả dependencies"
	@echo ""
	@echo "  make train        Train LightGBM với data thật"
	@echo ""
	@echo "  make server       Chạy dashboard (port 8000)"
	@echo "  make collector    Chạy data collector (Binance WS)"
	@echo "  make features     Chạy feature engine"
	@echo "  make signal       Chạy signal engine"
	@echo ""
	@echo "  make docker-up    Chạy toàn bộ project qua Docker"
	@echo "  make docker-down  Tắt Docker"
	@echo "  make docker-logs  Xem log Docker"
	@echo "  make docker-build Rebuild Docker image"
	@echo ""
	@echo "  make test         Chạy test suite"
	@echo "  make lint         Kiểm tra code style"
	@echo "  make clean        Xóa cache + build files"
	@echo ""

# ── Setup ────────────────────────────────────────────────────────
setup: venv install
	@echo "✓ Setup xong. Chạy 'make collector && make features' để bắt đầu thu thập data."

venv:
	python3 -m venv .venv
	@echo "✓ venv tạo tại .venv/"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r server/requirements.txt
	$(PIP) install -r collector/requirements.txt
	$(PIP) install -r feature_engine/requirements.txt
	$(PIP) install -r signal/requirements.txt
	$(PIP) install -r ml/requirements.txt
	@echo "✓ Dependencies installed"

# ── Data & Model ─────────────────────────────────────────────────
train:
	$(PYTHON) ml/train.py

auto-train:
	$(PYTHON) ml/auto_train.py

# ── Services ─────────────────────────────────────────────────────
server:
	cd server && $(abspath $(PYTHON)) manage.py runserver 0.0.0.0:8000

collector:
	$(PYTHON) collector/main.py

features:
	$(PYTHON) feature_engine/run.py

signal:
	$(PYTHON) signal/run.py

# ── Docker ───────────────────────────────────────────────────────
docker-up:
	docker compose -f docker/docker-compose.yml up

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

docker-build:
	docker compose -f docker/docker-compose.yml up --build

# ── Tests ────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

# ── Code quality ─────────────────────────────────────────────────
lint:
	$(PYTHON) -m flake8 ml/ collector/ feature_engine/ signal/ server/ \
	    --max-line-length=100 --ignore=E501,W503

# ── Cleanup ──────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.pyo" -delete 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/
	@echo "✓ Cleaned"
