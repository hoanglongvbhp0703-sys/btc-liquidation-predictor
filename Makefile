# ══════════════════════════════════════════════════════════════════
#  BTC Cascade Liquidation Predictor — Makefile
# ══════════════════════════════════════════════════════════════════

PYTHON  := .venv/bin/python
PIP     := .venv/bin/pip
SESSION := btc

.PHONY: help setup venv install \
        collector features auto-train signal server monitor \
        tmux status \
        train rebuild \
        docker-up docker-down docker-logs docker-build \
        test test-unit test-integration lint clean

# ── Default ──────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  BTC Cascade Liquidation Predictor"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  make setup        Bootstrap: venv + install deps"
	@echo ""
	@echo "  SERVICES (chạy trong terminal riêng)"
	@echo "  make collector    Binance WebSocket → data/*.csv"
	@echo "  make features     Build 46 features mỗi 1 phút"
	@echo "  make auto-train   Retrain model mỗi 1h"
	@echo "  make signal       Inference + paper trades"
	@echo "  make server       Dashboard http://localhost:8000"
	@echo ""
	@echo "  SHORTCUTS"
	@echo "  make tmux         Mở tất cả services trong tmux session '$(SESSION)'"
	@echo "  make status       Xem trạng thái tmux session"
	@echo "  make monitor      SHORT signal monitor (real-time)"
	@echo ""
	@echo "  MODEL"
	@echo "  make train        Train model thủ công"
	@echo "  make rebuild      Rebuild features_1m.csv từ raw data"
	@echo ""
	@echo "  DOCKER"
	@echo "  make docker-up    Chạy tất cả services qua Docker"
	@echo "  make docker-down  Tắt Docker"
	@echo "  make docker-logs  Xem log"
	@echo ""
	@echo "  DEV"
	@echo "  make test         Chạy test suite"
	@echo "  make lint         Flake8"
	@echo "  make clean        Xóa cache"
	@echo ""

# ── Setup ────────────────────────────────────────────────────────
setup: venv install
	@echo ""
	@echo "  Setup xong. Tiếp theo:"
	@echo "  1. cp .env.example .env  (set DJANGO_SECRET_KEY)"
	@echo "  2. make tmux             (chạy tất cả services)"

venv:
	python3 -m venv .venv
	@echo "✓ venv → .venv/"

install:
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt
	@echo "✓ Dependencies installed"

# ── Services ─────────────────────────────────────────────────────
collector:
	$(PYTHON) collector/main.py

features:
	$(PYTHON) feature_engine/run.py

auto-train:
	$(PYTHON) ml/auto_train.py

signal:
	$(PYTHON) signal/run.py

server:
	cd server && $(abspath $(PYTHON)) manage.py runserver 0.0.0.0:8000

monitor:
	$(PYTHON) scripts/monitor_short.py

# ── tmux shortcuts ────────────────────────────────────────────────
tmux:
	@tmux has-session -t $(SESSION) 2>/dev/null || tmux new-session -d -s $(SESSION) -n collector
	@tmux new-window   -t $(SESSION) -n collector  "$(PYTHON) collector/main.py; read" 2>/dev/null || true
	@tmux new-window   -t $(SESSION) -n features   "$(PYTHON) feature_engine/run.py; read"
	@tmux new-window   -t $(SESSION) -n auto_train "$(PYTHON) ml/auto_train.py; read"
	@tmux new-window   -t $(SESSION) -n signal     "$(PYTHON) signal/run.py; read"
	@tmux new-window   -t $(SESSION) -n server     "cd server && $(abspath $(PYTHON)) manage.py runserver 0.0.0.0:8000; read"
	@tmux new-window   -t $(SESSION) -n monitor    "$(PYTHON) scripts/monitor_short.py; read"
	@tmux attach -t $(SESSION)

status:
	@tmux list-windows -t $(SESSION) 2>/dev/null || echo "tmux session '$(SESSION)' không tồn tại"

# ── Model ─────────────────────────────────────────────────────────
train:
	$(PYTHON) ml/train.py

rebuild:
	$(PYTHON) scripts/rebuild_features.py

# ── Docker ───────────────────────────────────────────────────────
docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

docker-build:
	docker compose -f docker/docker-compose.yml build

# ── Tests ────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v

# ── Code quality ─────────────────────────────────────────────────
lint:
	$(PYTHON) -m flake8 ml/ collector/ feature_engine/ signal/ server/ scripts/ \
	    --max-line-length=100 --ignore=E501,W503

# ── Cleanup ──────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -o -name "*.pyo" | xargs rm -f 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/
	@echo "✓ Cleaned"
