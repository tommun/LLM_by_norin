@echo off
echo ====================================================
echo Starting Local GPU LLM Backend (FastAPI + CUDA)...
echo Target GPU: NVIDIA GeForce RTX 4070 Ti
echo ====================================================

cd /d "%~dp0"
call .\.venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
