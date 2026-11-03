import os

dst = r"H:\LLM_by_norin"
if os.path.exists(dst):
    for entry in os.listdir(dst):
        ep = os.path.join(dst, entry)
        if os.path.isdir(ep):
            count = len(os.listdir(ep))
            print(f"Directory: {entry} ({count} items)")
        else:
            size_kb = os.path.getsize(ep) / 1024
            print(f"File: {entry} ({size_kb:.1f} KB)")
