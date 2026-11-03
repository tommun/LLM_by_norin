import sys
import time
import urllib.request
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

job_id = sys.argv[1] if len(sys.argv) > 1 else ""
if not job_id:
    print("Usage: python watch_job.py <job_id>")
    sys.exit(1)

url = f"http://127.0.0.1:8000/api/video/jobs/{job_id}"
last_text = ""
last_prog = -1

for _ in range(60):
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            status = data.get("status")
            progress = data.get("progress")
            status_text = data.get("status_text")
            
            if progress != last_prog or status_text != last_text:
                print(f"[{progress}%] status={status}: {status_text}")
                last_prog = progress
                last_text = status_text

            if status in ("completed", "failed"):
                if status == "completed":
                    print(f"DONE: video_url={data.get('video_url')}")
                else:
                    print(f"FAILED: error={data.get('error_message')}")
                break
    except Exception as e:
        print(f"Error checking: {e}")
    time.sleep(3)
