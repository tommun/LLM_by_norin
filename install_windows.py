import os
import sys
import subprocess

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = os.path.join(PROJECT_ROOT, "backend", ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = os.path.join(PROJECT_ROOT, "backend", ".venv", "Scripts", "python.exe")

LAUNCH_SCRIPT = os.path.join(PROJECT_ROOT, "app_desktop_win.py")
ICON_FILE = os.path.join(PROJECT_ROOT, "icon.ico")

# Desktop path
desktop_dir = os.path.join(os.environ["USERPROFILE"], "Desktop")
shortcut_path = os.path.join(desktop_dir, "LLM & Image Studio.lnk")

# Start menu path
start_menu_dir = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
start_shortcut_path = os.path.join(start_menu_dir, "LLM & Image Studio.lnk")

def create_shortcut(target_lnk, target_exe, args, working_dir, icon_path, desc):
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{target_lnk}')
    $Shortcut.TargetPath = '{target_exe}'
    $Shortcut.Arguments = '"{args}"'
    $Shortcut.WorkingDirectory = '{working_dir}'
    $Shortcut.IconLocation = '{icon_path}'
    $Shortcut.Description = '{desc}'
    $Shortcut.Save()
    """
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode == 0:
        print(f"[SUCCESS] Created shortcut: {target_lnk}")
    else:
        print(f"[ERROR] Error creating shortcut: {res.stderr}")

# 1. Install pywebview into backend venv if missing
pip_exe = os.path.join(PROJECT_ROOT, "backend", ".venv", "Scripts", "pip.exe")
print("Installing pywebview for native Windows desktop window...")
subprocess.run([pip_exe, "install", "pywebview"], capture_output=True)

# 2. Create Desktop Shortcut
print("Creating Desktop shortcut...")
create_shortcut(
    shortcut_path,
    PYTHON_EXE,
    LAUNCH_SCRIPT,
    PROJECT_ROOT,
    ICON_FILE,
    "LLM & Image Studio (Luka AI) - Local GPU AI Creative Suite"
)

# 3. Create Start Menu Shortcut
print("Creating Start Menu shortcut...")
create_shortcut(
    start_shortcut_path,
    PYTHON_EXE,
    LAUNCH_SCRIPT,
    PROJECT_ROOT,
    ICON_FILE,
    "LLM & Image Studio (Luka AI) - Local GPU AI Creative Suite"
)

# 4. Create a portable batch launcher in project root as well
bat_launcher = os.path.join(PROJECT_ROOT, "起動する.bat")
with open(bat_launcher, "w", encoding="cp932") as f:
    f.write(f"""@echo off
chcp 65001 > nul
cd /d "{PROJECT_ROOT}"
start "" "{PYTHON_EXE}" "{LAUNCH_SCRIPT}"
exit
""")
print(f"[SUCCESS] Created batch launcher: {bat_launcher}")

print("\n=== Windows Installation Complete! ===")
print(f"Desktop shortcut created at: {shortcut_path}")
