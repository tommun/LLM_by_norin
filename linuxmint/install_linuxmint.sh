#!/usr/bin/env bash
# ==============================================================================
# LLM & Image Studio - Linux Mint Automatic Installer & Setup Script
# Supports: Linux Mint 21 (Vanessa/Vera/Victoria/Virginia), Linux Mint 22 (Wilma), Ubuntu 22.04/24.04
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "=========================================================="
echo "  🎨 LLM & Image Studio - Linux Mint Installer"
echo "=========================================================="
echo "Target Directory: $PROJECT_ROOT"

# 1. Update package lists & install required system libraries
echo "📦 Step 1: Installing system dependencies via apt..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y \
        python3 python3-pip python3-venv python3-dev \
        build-essential git curl libgl1 libglib2.0-0 \
        libgirepository1.0-dev libcairo2-dev pkg-config \
        gir1.2-webkit2-4.0 libwebkit2gtk-4.0-dev || true
fi

# 2. Check Node.js and npm for frontend
echo "📦 Step 2: Checking Node.js and npm..."
if ! command -v node &> /dev/null; then
    echo "⚡ Node.js not detected. Installing Node.js LTS via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node.js version: $(node -v)"
echo "npm version: $(npm -v)"

# 3. Create Python virtual environment
echo "📦 Step 3: Setting up Python virtual environment..."
cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created virtual environment at $BACKEND_DIR/.venv"
fi
source .venv/bin/activate
pip install --upgrade pip setuptools wheel

# 4. Install PyTorch with CUDA support
echo "📦 Step 4: Installing PyTorch with NVIDIA CUDA 12.1..."
if command -v nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA GPU detected:"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
else
    echo "⚠️ NVIDIA GPU not detected. Installing standard CPU PyTorch..."
    pip install torch torchvision torchaudio
fi

# 5. Install backend Python dependencies
echo "📦 Step 5: Installing backend dependencies..."
if [ -f "$BACKEND_DIR/requirements.txt" ]; then
    pip install -r "$BACKEND_DIR/requirements.txt"
fi

# Install desktop GUI wrapper & extra accelerators
pip install pywebview PyQt5 diffusers transformers accelerate safetensors uvicorn fastapi pydantic discord.py

# 6. Build frontend
echo "📦 Step 6: Building frontend React application..."
cd "$FRONTEND_DIR"
npm install
npm run build
echo "✅ Frontend build completed successfully."

# 7. Make launch scripts executable
chmod +x "$SCRIPT_DIR/run_linuxmint.sh"
chmod +x "$SCRIPT_DIR/app_desktop.py"

# 8. Create Linux Mint Desktop Application Launcher (.desktop)
echo "📦 Step 7: Creating Linux Mint Application Menu launcher..."
ICON_PATH="$PROJECT_ROOT/frontend/public/favicon.ico"
if [ -f "$SCRIPT_DIR/icon.png" ]; then
    ICON_PATH="$SCRIPT_DIR/icon.png"
fi

DESKTOP_ENTRY_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_ENTRY_DIR"

cat <<EOF > "$DESKTOP_ENTRY_DIR/llm-image-studio.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=LLM & Image Studio
GenericName=AI Vision LLM & Image Generator
Comment=Local GPU Vision LLM, SDXL RealVisXL & LoRA Creative Suite
Exec="$SCRIPT_DIR/run_linuxmint.sh"
Icon=$ICON_PATH
Terminal=false
Categories=Graphics;Utility;Development;
StartupNotify=true
StartupWMClass=llm-image-studio
EOF

chmod +x "$DESKTOP_ENTRY_DIR/llm-image-studio.desktop"

# Also place on user's Desktop if ~/Desktop exists
if [ -d "$HOME/Desktop" ]; then
    cp "$DESKTOP_ENTRY_DIR/llm-image-studio.desktop" "$HOME/Desktop/"
    chmod +x "$HOME/Desktop/llm-image-studio.desktop"
    echo "✅ Created shortcut on your Linux Mint Desktop!"
fi

echo "=========================================================="
echo "  🎉 Installation Complete!"
echo "=========================================================="
echo "You can now launch the software in two easy ways:"
echo " 1. Open the Linux Mint Application Menu -> Graphics -> 'LLM & Image Studio'"
echo " 2. Or double-click the 'LLM & Image Studio' icon on your Desktop"
echo " 3. Or run directly: $SCRIPT_DIR/run_linuxmint.sh"
echo "=========================================================="
