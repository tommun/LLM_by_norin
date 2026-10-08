import asyncio
import json
import threading
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from model_engine import engine, DEFAULT_MODEL_ID

# Lifespan event to automatically load model at startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start loading the model in a background thread so the server starts immediately
    loader_thread = threading.Thread(target=engine.load_model, daemon=True)
    loader_thread.start()
    yield

app = FastAPI(title="Local GPU LLM Engine API", lifespan=lifespan)

# Allow CORS for local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message text")

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    max_new_tokens: int = Field(default=1024, ge=1, le=4096)

class ModelLoadRequest(BaseModel):
    model_id: str = Field(default=DEFAULT_MODEL_ID)

@app.get("/")
def read_root():
    return {
        "service": "Local GPU LLM Assistant Backend",
        "gpu": engine.get_gpu_info()["device_name"],
        "cuda_available": engine.get_gpu_info()["cuda_available"],
        "model_loaded": engine.is_ready,
        "is_loading": engine.is_loading,
    }

@app.get("/api/gpu")
@app.get("/api/status")
def get_status():
    return engine.get_gpu_info()

@app.post("/api/model/load")
def load_model_endpoint(req: ModelLoadRequest, background_tasks: BackgroundTasks):
    if engine.is_loading:
        return {"status": "busy", "message": "Model is already loading."}
    
    background_tasks.add_task(engine.load_model, req.model_id)
    return {"status": "started", "model_id": req.model_id, "message": f"Started loading {req.model_id}"}

@app.post("/api/chat")
async def chat_non_stream(request: ChatRequest):
    if not engine.is_ready:
        if engine.is_loading:
            raise HTTPException(status_code=503, detail="Model is still loading into GPU. Please wait a moment.")
        else:
            raise HTTPException(status_code=500, detail=f"Model not loaded. Error: {engine.last_error}")

    try:
        messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
        # Collect full stream response
        full_response = ""
        for token in engine.stream_generate(
            messages=messages_dict,
            max_new_tokens=request.max_new_tokens,
            temperature=request.temperature,
            top_p=request.top_p
        ):
            full_response += token

        return {"response": full_response, "model": engine.model_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not engine.is_ready:
        if engine.is_loading:
            raise HTTPException(status_code=503, detail="Model is currently loading into GPU memory. Please wait.")
        else:
            raise HTTPException(status_code=500, detail=f"Model failed to load: {engine.last_error}")

    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]

    def event_generator():
        try:
            for token in engine.stream_generate(
                messages=messages_dict,
                max_new_tokens=request.max_new_tokens,
                temperature=request.temperature,
                top_p=request.top_p
            ):
                data = json.dumps({"token": token, "done": False}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            # Signal completion
            yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"
        except Exception as e:
            error_data = json.dumps({"error": str(e), "done": True}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
