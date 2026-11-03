#!/usr/bin/env bash
# ==============================================================================
# LLM & Image Studio - Linux Mint Launcher
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "=========================================================="
echo "  🚀 Starting LLM & Image Studio for Linux Mint"
echo "=========================================================="

# 1. Activate Python virtual environment if it exists
if [ -d "$BACKEND_DIR/.venv" ]; then
    echo "📦 Activating virtual environment..."
    source "$BACKEND_DIR/.venv/bin/activate"
elif [ -d "$PROJECT_ROOT/.venv" ]; then
    echo "📦 Activating root virtual environment..."
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# 2. Check if pywebview is available for native window, install if missing
if ! python3 -c "import webview" &>/dev/null; then
    echo "💡 Installing pywebview for native desktop GUI window..."
    pip install pywebview PyQt5 &>/dev/null || pip install pywebview &>/dev/null || true
fi

# 3. Launch native desktop application wrapper
python3 "$SCRIPT_DIR/app_desktop.py"
