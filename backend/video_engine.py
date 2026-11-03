import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import time
import io
import gc
import base64
import threading
from typing import Optional, Dict, Any, Union, Callable
from PIL import Image, ImageOps
import torch

from diffusers import WanImageToVideoPipeline, AutoencoderKLWan, WanTransformer3DModel
from diffusers.utils import export_to_video

# Directories
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BACKEND_DIR, "..", "outputs")
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

DEFAULT_WAN_MODEL_ID = os.getenv("WAN_MODEL_ID", "Wan-AI/Wan2.2-TI2V-5B-Diffusers")

class VideoEngine:
    """
    Image-to-Video Engine using Wan 2.2 TI2V-5B.
    Optimized for RTX 4070 Ti (12GB VRAM) using FP8/BF16, model CPU offload,
    and tiled VAE decoding.
    """
    def __init__(self, model_id: str = DEFAULT_WAN_MODEL_ID):
        self.model_id = model_id
        self.pipe: Optional[WanImageToVideoPipeline] = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        self.is_loading = False
        self.last_error: Optional[str] = None
        self.lock = threading.Lock()

    def load_model(self) -> bool:
        """Load Wan 2.2 TI2V pipeline with memory optimizations"""
        with self.lock:
            if self.is_ready and self.pipe is not None:
                return True

            self.is_loading = True
            self.last_error = None
            print(f"[VideoEngine] Loading Wan 2.2 model: {self.model_id}...")

            try:
                # Orchestrator handover
                from vram_orchestrator import orchestrator
                orchestrator.acquire("video")

                dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

                print(f"[VideoEngine] Initializing WanImageToVideoPipeline with dtype={dtype} (low_cpu_mem_usage=True)...")
                self.pipe = WanImageToVideoPipeline.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    low_cpu_mem_usage=True
                )

                if torch.cuda.is_available():
                    # TF32 for fast TensorCore matmul
                    torch.backends.cuda.matmul.allow_tf32 = True
                    torch.backends.cudnn.allow_tf32 = True

                    # Memory optimizations:
                    # 1. Enable model CPU offload: Stages T5, Transformer (DiT), and VAE sequentially on GPU
                    self.pipe.enable_model_cpu_offload()

                    # 2. Attention Slicing: Drastically reduces 3D Attention activation memory
                    try:
                        self.pipe.enable_attention_slicing()
                        print("[VideoEngine] Attention slicing enabled.")
                    except Exception as ae:
                        print(f"[VideoEngine] Attention slicing warning: {ae}")

                    # 3. VAE Tiling & Slicing: Prevents OOM during frame decoding
                    if hasattr(self.pipe, "vae") and self.pipe.vae is not None:
                        try:
                            self.pipe.vae.enable_tiling()
                            self.pipe.vae.enable_slicing()
                        except Exception as ve:
                            print(f"[VideoEngine] VAE tiling warning: {ve}")

                self.is_ready = True
                self.is_loading = False
                print(f"[VideoEngine] Wan 2.2 model successfully loaded and ready! Peak VRAM: {orchestrator.get_vram_stats()['max_allocated_mb']}MB")
                return True

            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                import traceback
                print(f"[VideoEngine] Error loading Wan 2.2 model: {e}", file=sys.stderr)
                traceback.print_exc()
                return False

    def unload_model(self):
        """Completely unload Wan 2.2 from VRAM"""
        with self.lock:
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
            if self.pipe is not None:
                print("[VideoEngine] Unloading Wan 2.2 from GPU...")
                del self.pipe
                self.pipe = None
            self.is_ready = False
            import gc
            for _ in range(3):
                gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("[VideoEngine] Wan 2.2 unloaded. GPU VRAM completely freed.")

    def _prepare_keyframe(self, image_input: Union[str, Image.Image], target_width: int = 832, target_height: int = 480) -> Image.Image:
        """Convert DataURL, file path, or PIL Image into correctly sized RGB Image"""
        img: Optional[Image.Image] = None
        if isinstance(image_input, Image.Image):
            img = image_input
        elif isinstance(image_input, str):
            if image_input.startswith("data:image"):
                _, b64data = image_input.split(",", 1)
                img = Image.open(io.BytesIO(base64.b64decode(b64data)))
            elif os.path.exists(image_input):
                img = Image.open(image_input)
            else:
                raise ValueError(f"Invalid image input format or file does not exist: {image_input[:50]}")
        else:
            raise TypeError(f"Unsupported image input type: {type(image_input)}")

        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Resize keeping aspect ratio, crop center to target dimensions
        img = ImageOps.fit(img, (target_width, target_height), Image.Resampling.LANCZOS)
        return img

    def generate(
        self,
        keyframe_image: Union[str, Image.Image],
        motion_prompt: str,
        negative_prompt: Optional[str] = None,
        num_frames: int = 81,
        fps: int = 16,
        num_inference_steps: int = 30,
        guidance_scale: float = 5.0,
        seed: Optional[int] = None,
        width: int = 832,
        height: int = 480,
        output_filename: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Generate ~5-second MP4 video clip from keyframe image + motion prompt.
        """
        # Ensure VRAM orchestration
        from vram_orchestrator import orchestrator
        orchestrator.acquire("video")

        if not self.is_ready or self.pipe is None:
            success = self.load_model()
            if not success or self.pipe is None:
                raise RuntimeError(f"Failed to load Wan 2.2 model: {self.last_error}")

        # Prepare Keyframe
        pil_image = self._prepare_keyframe(keyframe_image, target_width=width, target_height=height)

        # Seed & Generator
        if seed is None or seed < 0:
            seed = torch.randint(0, 2**32 - 1, (1,)).item()
        generator = torch.Generator(device="cpu").manual_seed(seed)

        # Mandatory negative prompt ensuring content safety (underage exclusion)
        safe_negative = "child, loli, teen, underage, school uniform, static, low quality, distorted, blurry, jerky, frame drops"
        if negative_prompt:
            safe_negative = f"{negative_prompt}, {safe_negative}"

        print(f"[VideoEngine] Generating video ({width}x{height}, {num_frames} frames @ {fps}fps, {num_inference_steps} steps, seed={seed})...")
        print(f"[VideoEngine] Motion prompt: '{motion_prompt}'")
        start_time = time.time()

        def step_end_callback(pipe, step_idx, timestep, callback_kwargs):
            if progress_callback:
                try:
                    progress_callback(step_idx + 1, num_inference_steps)
                except Exception:
                    pass
            return callback_kwargs

        try:
            output = self.pipe(
                image=pil_image,
                prompt=motion_prompt,
                negative_prompt=safe_negative,
                height=height,
                width=width,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
                callback_on_step_end=step_end_callback
            )

            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass

            frames = output.frames[0]  # list of PIL images or numpy arrays
            elapsed_sec = round(time.time() - start_time, 2)
            peak_vram = orchestrator.get_vram_stats()["max_allocated_mb"]
            print(f"[VideoEngine] Video frames generated in {elapsed_sec}s! Peak VRAM: {peak_vram}MB")

            # Save to MP4 file
            if not output_filename:
                timestamp = int(time.time())
                output_filename = f"video_{timestamp}_{seed % 10000}.mp4"

            if not output_filename.endswith(".mp4"):
                output_filename += ".mp4"

            video_filepath = os.path.join(OUTPUTS_DIR, output_filename)
            export_to_video(frames, video_filepath, fps=fps)
            print(f"[VideoEngine] Exported video to {video_filepath} ({os.path.getsize(video_filepath)} bytes)")

            # Also save keyframe image for visual reference in gallery
            base_name = os.path.splitext(output_filename)[0]
            keyframe_filename = f"{base_name}_keyframe.png"
            keyframe_filepath = os.path.join(OUTPUTS_DIR, keyframe_filename)
            pil_image.save(keyframe_filepath, format="PNG")

            result = {
                "status": "success",
                "filename": output_filename,
                "video_url": f"/outputs/{output_filename}",
                "keyframe_url": f"/outputs/{keyframe_filename}",
                "motion_prompt": motion_prompt,
                "negative_prompt": safe_negative,
                "num_frames": num_frames,
                "fps": fps,
                "duration_seconds": round(num_frames / fps, 2),
                "width": width,
                "height": height,
                "seed": seed,
                "steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "elapsed_seconds": elapsed_sec,
                "peak_vram_mb": peak_vram,
                "model_id": self.model_id
            }

            # Save metadata JSON for gallery
            meta_filepath = os.path.join(OUTPUTS_DIR, f"{base_name}.json")
            import json
            with open(meta_filepath, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            return result

        except Exception as e:
            import traceback
            print(f"[VideoEngine] Generation error occurred: {e}", file=sys.stderr)
            traceback.print_exc()
            raise e
        finally:
            # Automatic unloading to immediately restore clean VRAM state
            self.unload_model()
            orchestrator.release()

# Global singleton
video_engine = VideoEngine()
