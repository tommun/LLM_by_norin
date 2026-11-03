import os
import shutil

for d in ["C", "D", "E", "F", "G", "H", "I", "J"]:
    path = f"{d}:\\"
    if os.path.exists(path):
        try:
            usage = shutil.disk_usage(path)
            total = usage.total / (1024**3)
            free = usage.free / (1024**3)
            try:
                items = os.listdir(path)
                preview = items[:8]
            except Exception as e:
                preview = f"Cannot list: {e}"
            print(f"=== Drive {d}: ===")
            print(f"  Total: {total:.2f} GB")
            print(f"  Free:  {free:.2f} GB")
            print(f"  Top items: {preview}")
        except Exception as e:
            print(f"=== Drive {d}: === (Error: {e})")
