import asyncio
import base64
import json
import os
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from model_engine import engine, DEFAULT_MODEL_ID
from image_engine import image_engine

# Lifespan event to automatically load Vision LLM model at startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    loader_thread = threading.Thread(target=engine.load_model, daemon=True)
    loader_thread.start()
    yield

app = FastAPI(title="Local GPU Vision-LLM & Image Studio API", lifespan=lifespan)

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
    images: Optional[List[str]] = Field(default=None, description="Optional Base64/DataURL images")

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
    guidance_scale: float = Field(default=0.0, ge=0.0, le=5.0)
    seed: Optional[int] = Field(default=None)
    width: int = Field(default=512, ge=256, le=768)
    height: int = Field(default=512, ge=256, le=768)

class GitSyncRequest(BaseModel):
    image_data_urls: Optional[List[str]] = Field(default=None)
    commit_message: Optional[str] = Field(default="chore: sync generated images and chat outputs")

@app.get("/")
def read_root():
    gpu_info = engine.get_gpu_info()
    return {
        "service": "Local GPU Vision LLM & Image Studio Backend",
        "gpu": gpu_info["device_name"],
        "cuda_available": gpu_info["cuda_available"],
        "vision_llm_loaded": engine.is_ready,
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
            raise HTTPException(status_code=503, detail="Vision Model is still loading into GPU. Please wait a moment.")
        else:
            raise HTTPException(status_code=500, detail=f"Model not loaded. Error: {engine.last_error}")

    try:
        messages_dict = [
            {"role": m.role, "content": m.content, "images": m.images or []}
            for m in request.messages
        ]
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
            raise HTTPException(status_code=503, detail="Vision Model is currently loading into GPU memory. Please wait.")
        else:
            raise HTTPException(status_code=500, detail=f"Model failed to load: {engine.last_error}")

    messages_dict = [
        {"role": m.role, "content": m.content, "images": m.images or []}
        for m in request.messages
    ]

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

@app.post("/api/git/sync-outputs")
async def sync_outputs_to_git(req: GitSyncRequest):
    try:
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        outputs_dir = os.path.join(repo_dir, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)

        saved_files = []
        if req.image_data_urls:
            for idx, data_url in enumerate(req.image_data_urls):
                if "," in data_url:
                    header, b64data = data_url.split(",", 1)
                    raw_bytes = base64.b64decode(b64data)
                    filename = f"image_{int(time.time())}_{idx}.png"
                    filepath = os.path.join(outputs_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(raw_bytes)
                    saved_files.append(filename)

        # Git add, commit, push
        subprocess.run(["git", "add", "outputs/"], cwd=repo_dir, check=True)
        commit_res = subprocess.run(
            ["git", "commit", "-m", req.commit_message or "chore: sync outputs"],
            cwd=repo_dir,
            capture_output=True,
            text=True
        )
        push_res = subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, capture_output=True, text=True)

        return {
            "status": "success",
            "saved_count": len(saved_files),
            "files": saved_files,
            "commit_output": commit_res.stdout,
            "push_output": push_res.stdout
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Git sync failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
