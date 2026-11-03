import os
import shutil

src = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin"
dst = r"H:\LLM_by_norin"

files_to_sync = [
    os.path.join("backend", "main.py"),
    os.path.join("frontend", "src", "App.tsx"),
    os.path.join("frontend", "src", "style.css"),
    os.path.join("frontend", "package.json"),
]

for rel in files_to_sync:
    sf = os.path.join(src, rel)
    df = os.path.join(dst, rel)
    if os.path.exists(sf):
        os.makedirs(os.path.dirname(df), exist_ok=True)
        shutil.copy2(sf, df)
        print(f"Synced {rel}")

# Sync frontend/dist folder
s_dist = os.path.join(src, "frontend", "dist")
d_dist = os.path.join(dst, "frontend", "dist")
if os.path.exists(s_dist):
    if os.path.exists(d_dist):
        shutil.rmtree(d_dist)
    shutil.copytree(s_dist, d_dist)
    print("Synced frontend/dist")

print("All gallery updates synced to USB H:!")
