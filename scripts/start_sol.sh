#!/bin/bash
# start_sol.sh — Khởi động pipeline SOL (song song với BTC pipeline)
#
# Cách dùng:
#   bash scripts/start_sol.sh
#
# Session tmux: sol
# Data dir:     data/sol/
# ML artifacts: ml/artifacts/sol/

set -e

SESSION="sol"
ROOT="/home/coder"
PYTHON="$ROOT/.venv/bin/python3"
SYMBOL="SOLUSDT"
SPOT_SYMBOL="SOLUSDT"
SUBDIR="sol"

# Tắt session cũ nếu đang chạy
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Tạo session mới
tmux new-session -d -s "$SESSION" -x 220 -y 50

# Window 0: Collector (8 streams)
tmux rename-window -t "$SESSION:0" "collector"
tmux send-keys -t "$SESSION:0" \
    "cd $ROOT && SYMBOL=$SYMBOL SPOT_SYMBOL=$SPOT_SYMBOL DATA_SUBDIR=$SUBDIR $PYTHON collector/main.py" \
    Enter

# Window 1: Feature Engine
tmux new-window -t "$SESSION" -n "features"
tmux send-keys -t "$SESSION:1" \
    "cd $ROOT && SYMBOL=$SYMBOL DATA_SUBDIR=$SUBDIR $PYTHON feature_engine/run.py" \
    Enter

# Window 2: Signal / Inference
tmux new-window -t "$SESSION" -n "signal"
tmux send-keys -t "$SESSION:2" \
    "cd $ROOT && SYMBOL=$SYMBOL DATA_SUBDIR=$SUBDIR $PYTHON signal/run.py" \
    Enter

# Window 3: Auto-train
tmux new-window -t "$SESSION" -n "auto_train"
tmux send-keys -t "$SESSION:3" \
    "cd $ROOT && SYMBOL=$SYMBOL DATA_SUBDIR=$SUBDIR $PYTHON ml/auto_train.py" \
    Enter

echo "✅ SOL pipeline đã khởi động trên tmux session '$SESSION'"
echo ""
echo "Attach:  tmux attach -t $SESSION"
echo "Windows: collector | features | signal | auto_train"
echo "Data:    $ROOT/data/$SUBDIR/"
echo "Models:  $ROOT/ml/artifacts/$SUBDIR/"
