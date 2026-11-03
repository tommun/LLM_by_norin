import os

p = r"H:\LLM_by_norin\backend\models"
if os.path.exists(p):
    for f in os.listdir(p):
        fp = os.path.join(p, f)
        print(f, f"{os.path.getsize(fp) / (1024*1024):.1f} MB")
else:
    print("models does not exist yet")
