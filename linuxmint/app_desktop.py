#!/usr/bin/env python3
"""
LLM & Image Studio - Linux Mint Native Desktop Client
Wraps the full React studio + FastAPI backend into a seamless, native Linux Mint desktop application.
Features:
- Automatic backend lifecycle management (starts FastAPI, monitors health, clean shutdown on exit)
- Native WebKit2GTK window integration with Cinnamon/MATE desktop
- Real-time GPU & VRAM monitoring, Vision LLM, SDXL RealVisXL, img2img remake, and ControlNet
"""

import os
import sys
import time
import signal
import subprocess
import threading
import urllib.request
import urllib.error

# Determine base paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

BACKEND_PORT = 8000
FRONTEND_PORT = 5173
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

backend_process = None
frontend_process = None
is_shutting_down = False

def is_server_ready(url: str, timeout: float = 1.0) -> bool:
    """Check if server is responding"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status in (200, 304)
    except Exception:
        return False

def start_backend():
    """Launch the FastAPI backend in the background"""
    global backend_process
    print("[Studio Launcher] Checking backend server...")
    if is_server_ready(BACKEND_URL):
        print("[Studio Launcher] Backend server is already running!")
        return

    python_bin = sys.executable
    # Check for venv python
    venv_py = os.path.join(BACKEND_DIR, ".venv", "bin", "python")
    if os.path.exists(venv_py):
        python_bin = venv_py

    cmd = [python_bin, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)]
    print(f"[Studio Launcher] Starting backend server: {' '.join(cmd)}")
    env = os.environ.copy()
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    backend_process = subprocess.Popen(cmd, cwd=BACKEND_DIR, env=env)

def start_frontend_if_needed():
    """Check if frontend dev server or built static files should be served"""
    global frontend_process
    if is_server_ready(FRONTEND_URL):
        print("[Studio Launcher] Frontend dev server is already running!")
        return FRONTEND_URL

    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    if os.path.exists(dist_dir) and os.path.exists(os.path.join(dist_dir, "index.html")):
        # Serve static build using a simple python http server on 5173
        print(f"[Studio Launcher] Serving built frontend from {dist_dir}...")
        cmd = [sys.executable, "-m", "http.server", str(FRONTEND_PORT), "--directory", dist_dir]
        frontend_process = subprocess.Popen(cmd, cwd=dist_dir)
        return FRONTEND_URL

    # If npm is available, run dev
    npm_bin = "npm"
    cmd = [npm_bin, "run", "dev", "--", "--port", str(FRONTEND_PORT), "--host"]
    print(f"[Studio Launcher] Starting frontend dev server: {' '.join(cmd)}")
    frontend_process = subprocess.Popen(cmd, cwd=FRONTEND_DIR)
    return FRONTEND_URL

def cleanup():
    """Safely terminate child processes on exit to release GPU VRAM"""
    global is_shutting_down, backend_process, frontend_process
    if is_shutting_down:
        return
    is_shutting_down = True
    print("\n[Studio Launcher] Shutting down application and freeing GPU memory...")

    if backend_process and backend_process.poll() is None:
        try:
            backend_process.terminate()
            backend_process.wait(timeout=3)
        except Exception:
            backend_process.kill()

    if frontend_process and frontend_process.poll() is None:
        try:
            frontend_process.terminate()
            frontend_process.wait(timeout=3)
        except Exception:
            frontend_process.kill()

    print("[Studio Launcher] All services safely stopped.")

def main():
    # Register termination signals
    signal.signal(signal.SIGINT, lambda sig, frame: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(0))

    start_backend()
    target_url = start_frontend_if_needed()

    # Wait for backend and frontend to be responsive
    print("[Studio Launcher] Waiting for servers to initialize...")
    for _ in range(30):
        if is_server_ready(target_url):
            break
        time.sleep(1)

    # Launch desktop window via pywebview
    try:
        import webview
        print("[Studio Launcher] Launching Linux Mint native GUI window via pywebview...")
        window = webview.create_window(
            title="LLM & Image Studio (Luka AI) - Linux Mint Edition",
            url=target_url,
            width=1380,
            height=860,
            min_size=(1024, 700),
            background_color="#0F172A",
            text_select=True
        )
        webview.start(debug=False)
    except ImportError:
        print("\n[Studio Launcher] Note: 'pywebview' is not installed.")
        print("[Studio Launcher] Opening application in your default Linux Mint browser...")
        import webbrowser
        webbrowser.open(target_url)
        print("\nPress Ctrl+C to stop the servers.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
