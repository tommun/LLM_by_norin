import os
from PIL import Image

src_png = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\linuxmint\icon.png"
dst_ico = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\icon.ico"

if os.path.exists(src_png):
    img = Image.open(src_png)
    img.save(dst_ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Created icon.ico at {dst_ico}")
else:
    print("Source png not found")
