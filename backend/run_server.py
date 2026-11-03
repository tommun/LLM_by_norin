import sys
import uvicorn

if __name__ == "__main__":
    print("Starting uvicorn server on 0.0.0.0:8000...", flush=True)
    try:
        import main
        print("Imported main successfully! Running uvicorn...", flush=True)
        uvicorn.run(main.app, host="0.0.0.0", port=8000, log_level="info")
    except Exception as e:
        print(f"Failed to start: {e}", flush=True)
