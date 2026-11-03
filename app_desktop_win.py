import os
import sys
import time
import subprocess
import threading
import urllib.request
import webbrowser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

BACKEND_PORT = 8000
FRONTEND_PORT = 5173
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

backend_proc = None
frontend_proc = None
bot_proc = None
is_exiting = False

def is_online(url, timeout=1.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status in (200, 304)
    except Exception:
        return False

def start_backend():
    global backend_proc
    if is_online(BACKEND_URL):
        print("[Studio Windows] Backend is already running.")
        return

    py_bin = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py_bin):
        py_bin = sys.executable

    cmd = [py_bin, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)]
    print(f"[Studio Windows] Starting backend: {' '.join(cmd)}")
    env = os.environ.copy()
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    backend_proc = subprocess.Popen(cmd, cwd=BACKEND_DIR, env=env)

def start_frontend():
    global frontend_proc
    if is_online(FRONTEND_URL):
        print("[Studio Windows] Frontend dev server is already running.")
        return FRONTEND_URL

    dist_dir = os.path.join(FRONTEND_DIR, "dist")
    if os.path.exists(dist_dir) and os.path.exists(os.path.join(dist_dir, "index.html")):
        print(f"[Studio Windows] Serving production frontend from {dist_dir}...")
        py_bin = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
        if not os.path.exists(py_bin):
            py_bin = sys.executable
        cmd = [py_bin, "-m", "http.server", str(FRONTEND_PORT), "--directory", dist_dir]
        frontend_proc = subprocess.Popen(cmd, cwd=dist_dir)
        return FRONTEND_URL

    cmd = ["cmd", "/c", "npm", "run", "dev", "--", "--port", str(FRONTEND_PORT)]
    frontend_proc = subprocess.Popen(cmd, cwd=FRONTEND_DIR)
    return FRONTEND_URL

def start_discord_bot_background():
    global bot_proc
    py_bin = os.path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py_bin):
        py_bin = sys.executable
    bot_script = os.path.join(BACKEND_DIR, "discord_bot.py")
    if os.path.exists(bot_script):
        print("[Studio Windows] Starting Discord Bot in background...")
        bot_proc = subprocess.Popen([py_bin, "discord_bot.py"], cwd=BACKEND_DIR)

def cleanup():
    global is_exiting, backend_proc, frontend_proc, bot_proc
    if is_exiting:
        return
    is_exiting = True
    print("\n[Studio Windows] Stopping background processes...")
    for p in [backend_proc, frontend_proc, bot_proc]:
        if p and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                p.kill()
    print("[Studio Windows] Cleanup complete.")

def main():
    print("==================================================")
    print("  🚀 LLM & Image Studio (Luka AI) - Windows")
    print("==================================================")
    
    start_backend()
    target_url = start_frontend()
    # Also start Discord bot so user can use both GUI and Discord simultaneously!
    start_discord_bot_background()

    print("[Studio Windows] Waiting for services to initialize...")
    for _ in range(25):
        if is_online(target_url):
            break
        time.sleep(1)

    # Launch desktop window
    try:
        import webview
        print("[Studio Windows] Launching native Edge/WebView2 desktop window...")
        window = webview.create_window(
            title="LLM & Image Studio (Luka AI)",
            url=target_url,
            width=1400,
            height=880,
            min_size=(1024, 700),
            background_color="#0F172A",
            text_select=True
        )
        webview.start()
    except Exception as e:
        print(f"[Studio Windows] Opening in default browser: {e}")
        webbrowser.open(target_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
