import os

main_path = r"C:\Users\owner\.gemini\antigravity\scratch\LLM_by_norin\backend\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add StaticFiles import
if "from fastapi.staticfiles import StaticFiles" not in code:
    code = code.replace(
        "from fastapi.responses import StreamingResponse",
        "from fastapi.responses import StreamingResponse\nfrom fastapi.staticfiles import StaticFiles"
    )

# 2. Add OUTPUTS_DIR mount and helper functions
outputs_setup = '''
# ========================================================
# Output & Gallery Static Files and Auto-Saving
# ========================================================
OUTPUTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
os.makedirs(OUTPUTS_DIR, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

def save_generated_image_to_outputs(img_data_url: str, metadata: dict) -> str:
    """Save generated image base64 data and metadata json to outputs/ directory"""
    try:
        timestamp = int(time.time())
        seed = metadata.get("seed", 0)
        filename_base = f"image_{timestamp}_{seed}"
        img_filename = f"{filename_base}.png"
        meta_filename = f"{filename_base}.json"

        img_path = os.path.join(OUTPUTS_DIR, img_filename)
        meta_path = os.path.join(OUTPUTS_DIR, meta_filename)

        if "," in img_data_url:
            raw_b64 = img_data_url.split(",", 1)[1]
            raw_bytes = base64.b64decode(raw_b64)
            with open(img_path, "wb") as f:
                f.write(raw_bytes)

            meta_data = {
                "filename": img_filename,
                "created_at": timestamp,
                "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
                **{k: v for k, v in metadata.items() if k not in ("image_url", "pose_skeleton_url")}
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            return f"/outputs/{img_filename}"
    except Exception as e:
        print(f"[Gallery] Error saving output image: {e}")
    return ""

@app.get("/api/gallery")
def get_gallery_images(limit: int = 200, offset: int = 0):
    """Retrieve list of all generated images with metadata, sorted by newest first"""
    try:
        items = []
        if os.path.exists(OUTPUTS_DIR):
            files = os.listdir(OUTPUTS_DIR)
            img_files = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
            
            # Sort by file modification time (newest first)
            img_files.sort(
                key=lambda f: os.path.getmtime(os.path.join(OUTPUTS_DIR, f)),
                reverse=True
            )

            for img_f in img_files[offset:offset + limit]:
                fp = os.path.join(OUTPUTS_DIR, img_f)
                stat = os.stat(fp)
                base_name = os.path.splitext(img_f)[0]
                meta_file = os.path.join(OUTPUTS_DIR, f"{base_name}.json")
                
                meta = {}
                if os.path.exists(meta_file):
                    try:
                        with open(meta_file, "r", encoding="utf-8") as mf:
                            meta = json.load(mf)
                    except Exception:
                        pass

                items.append({
                    "filename": img_f,
                    "url": f"/outputs/{img_f}",
                    "size_bytes": stat.st_size,
                    "created_at": int(stat.st_mtime),
                    "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                    "prompt": meta.get("prompt") or meta.get("final_prompt") or meta.get("original_prompt") or "",
                    "negative_prompt": meta.get("negative_prompt", ""),
                    "seed": meta.get("seed"),
                    "steps": meta.get("steps"),
                    "aspect_ratio": meta.get("aspect_ratio"),
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "model_id": meta.get("model_id"),
                    "lora_name": meta.get("lora_name"),
                    "elapsed_seconds": meta.get("elapsed_seconds")
                })

        return {
            "total_count": len(img_files) if os.path.exists(OUTPUTS_DIR) else 0,
            "items": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch gallery: {str(e)}")

@app.delete("/api/gallery/{filename}")
def delete_gallery_image(filename: str):
    """Delete an image and its metadata from outputs"""
    safe_name = os.path.basename(filename)
    img_path = os.path.join(OUTPUTS_DIR, safe_name)
    base_name = os.path.splitext(safe_name)[0]
    meta_path = os.path.join(OUTPUTS_DIR, f"{base_name}.json")

    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        os.remove(img_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)
        return {"status": "success", "deleted": safe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
'''

if "app.mount(\"/outputs\"" not in code:
    code = code.replace(
        'app.add_middleware(',
        outputs_setup + '\napp.add_middleware('
    )

# 3. Hook save_generated_image_to_outputs into /api/hq/generate
hq_save_hook = '''        result = hq_image_engine.generate(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            enhance_prompt=req.enhance_prompt,
            lora_name=req.lora_name,
            lora_scale=req.lora_scale,
            num_inference_steps=req.steps,
            guidance_scale=req.guidance_scale,
            aspect_ratio=req.aspect_ratio,
            seed=req.seed,
            pose_image=req.pose_image,
            controlnet_scale=req.controlnet_scale,
            init_image=req.init_image,
            denoise_strength=req.denoise_strength,
            model_engine=engine
        )
        # Automatically save to outputs gallery
        if result.get("image_url"):
            saved_url = save_generated_image_to_outputs(result["image_url"], result)
            result["saved_url"] = saved_url
        return result'''

old_hq_res = '''        result = hq_image_engine.generate(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            enhance_prompt=req.enhance_prompt,
            lora_name=req.lora_name,
            lora_scale=req.lora_scale,
            num_inference_steps=req.steps,
            guidance_scale=req.guidance_scale,
            aspect_ratio=req.aspect_ratio,
            seed=req.seed,
            pose_image=req.pose_image,
            controlnet_scale=req.controlnet_scale,
            init_image=req.init_image,
            denoise_strength=req.denoise_strength,
            model_engine=engine
        )
        return result'''

if old_hq_res in code:
    code = code.replace(old_hq_res, hq_save_hook)
    print("Successfully hooked auto-save into /api/hq/generate!")

with open(main_path, "w", encoding="utf-8") as f:
    f.write(code)

print("Saved main.py with gallery APIs and auto-save!")
