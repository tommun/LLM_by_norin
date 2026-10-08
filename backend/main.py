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
from image_engine import image_engine

# Lifespan event to automatically load LLM model at startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start loading the LLM model in background
    loader_thread = threading.Thread(target=engine.load_model, daemon=True)
    loader_thread.start()
    yield

app = FastAPI(title="Local GPU LLM & Image Gen Engine API", lifespan=lifespan)

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

class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt for image generation")
    steps: int = Field(default=1, ge=1, le=8, description="Inference steps (1-4 recommended for SD-Turbo)")
    guidance_scale: float = Field(default=0.0, ge=0.0, le=5.0, description="Guidance scale (0.0 for SD-Turbo)")
    seed: Optional[int] = Field(default=None, description="Random seed")
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=512, ge=256, le=768)

@app.get("/")
def read_root():
    gpu_info = engine.get_gpu_info()
    return {
        "service": "Local GPU LLM & Image Assistant Backend",
        "gpu": gpu_info["device_name"],
        "cuda_available": gpu_info["cuda_available"],
        "llm_loaded": engine.is_ready,
        "image_gen_loaded": image_engine.is_ready,
    }

@app.get("/api/gpu")
@app.get("/api/status")
def get_status():
    status = engine.get_gpu_info()
    status["image_model_id"] = image_engine.model_id
    status["image_model_loaded"] = image_engine.is_ready
    status["image_is_loading"] = image_engine.is_loading
    return status

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

@app.post("/api/generate-image")
async def generate_image_endpoint(req: ImageGenerateRequest):
    try:
        result = image_engine.generate(
            prompt=req.prompt,
            num_inference_steps=req.steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
            width=req.width,
            height=req.height
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
