import os

path = r"H:\LLM_by_norin"
if os.path.exists(path):
    total_bytes = 0
    file_count = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total_bytes += os.path.getsize(fp)
                file_count += 1
            except Exception:
                pass
    mb = total_bytes / (1024 * 1024)
    print(f"H:\\LLM_by_norin: {file_count} files, {mb:.2f} MB copied so far.")
else:
    print("H:\\LLM_by_norin does not exist yet.")
