import base64
import io
import os
import time
import threading
from typing import Optional, Dict, Any, List
import torch
from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler
from PIL import Image

DEFAULT_HQ_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
LORAS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "loras"))
os.makedirs(LORAS_DIR, exist_ok=True)

# Recommended resolutions for SDXL (divisible by 64 or 8)
HQ_ASPECT_RATIOS = {
    "1:1": {"width": 1024, "height": 1024, "label": "正方形 (1024×1024)"},
    "16:9": {"width": 1216, "height": 832, "label": "シネマ横長 (1216×832)"},
    "9:16": {"width": 832, "height": 1216, "label": "スマホ縦長 (832×1216)"},
    "4:3": {"width": 1152, "height": 896, "label": "写真横長 (1152×896)"},
    "3:4": {"width": 896, "height": 1152, "label": "ポスター縦長 (896×1152)"},
}

DEFAULT_NEGATIVE_PROMPT = (
    "ugly, deformed, noisy, blurry, low contrast, distorted anatomy, extra limbs, "
    "bad hands, missing fingers, poorly drawn face, mutated, disfigured, watermark, "
    "signature, text, low quality, artifacts"
)

class HighQualityImageEngine:
    """
    High-Quality SDXL Engine designed for RTX 4070 Ti (12GB VRAM).
    Focuses on maximum prompt fidelity, intricate details, and custom style LoRA transfer.
    """
    def __init__(self, model_id: str = DEFAULT_HQ_MODEL_ID):
        self.model_id = model_id
        self.pipe: Optional[StableDiffusionXLPipeline] = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error: Optional[str] = None
        self.current_lora: Optional[str] = None
        self.lock = threading.Lock()

    def get_available_loras(self) -> List[str]:
        if not os.path.exists(LORAS_DIR):
            return []
        files = os.listdir(LORAS_DIR)
        return [f for f in files if f.endswith(".safetensors") or f.endswith(".bin")]

    def load_model(self) -> bool:
        with self.lock:
            if self.is_ready and self.pipe is not None:
                return True

            self.is_loading = True
            self.last_error = None
            print(f"[HQEngine] Loading SDXL model: {self.model_id} on {self.device}...")

            try:
                # Clean CUDA cache before loading
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                self.pipe = StableDiffusionXLPipeline.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    variant="fp16" if torch.cuda.is_available() else None,
                    use_safetensors=True
                )

                # Set DPM++ 2M Karras Scheduler for clean, artful textures
                self.pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                    self.pipe.scheduler.config,
                    use_karras_sigmas=True,
                    algorithm_type="dpmsolver++"
                )

                # Put SDXL directly on CUDA GPU for lightning-fast inference
                if torch.cuda.is_available():
                    self.pipe = self.pipe.to("cuda")
                    if hasattr(self.pipe, "vae") and self.pipe.vae is not None:
                        if hasattr(self.pipe.vae, "enable_tiling"):
                            self.pipe.vae.enable_tiling()
                        if hasattr(self.pipe.vae, "enable_slicing"):
                            self.pipe.vae.enable_slicing()

                self.is_ready = True
                self.is_loading = False
                print(f"[HQEngine] SDXL {self.model_id} successfully loaded and ready for high-fidelity generation!")
                return True
            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                print(f"[HQEngine] Error loading SDXL model: {e}")
                return False

    def enhance_prompt_with_llm(self, user_prompt: str, model_engine) -> str:
        """
        Use the local Qwen2.5-VL-7B to enhance/expand user's prompt into
        a rich, Midjourney-caliber English masterpiece prompt.
        """
        if not model_engine or not model_engine.is_ready:
            return user_prompt

        system_instruction = (
            "You are a world-class prompt engineer for Midjourney v6 and SDXL. "
            "Transform the user's concept into an elaborate, masterfully composed English prompt. "
            "Detail the subject, lighting (e.g., golden hour, cinematic volumetric, chiaroscuro), "
            "textures, intricate details, artistic style, lens/shot angle, and overall mood. "
            "Keep it under 90 words. Output ONLY the English prompt without any preamble, quotes, or markdown."
        )

        try:
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Concept: {user_prompt}"}
            ]
            tokens = []
            for token in model_engine.stream_generate(
                messages=messages,
                max_new_tokens=150,
                temperature=0.7
            ):
                tokens.append(token)
            enhanced = "".join(tokens).strip().strip('"').strip("'")
            if enhanced:
                print(f"[HQEngine] Enhanced prompt: '{user_prompt}' -> '{enhanced}'")
                return enhanced
        except Exception as e:
            print(f"[HQEngine] Prompt enhancement failed, using original: {e}")
        return user_prompt

    def apply_lora(self, lora_name: Optional[str], lora_scale: float = 0.8):
        if not self.pipe:
            return

        if not lora_name:
            if self.current_lora:
                try:
                    self.pipe.unload_lora_weights()
                    self.current_lora = None
                    print("[HQEngine] Unloaded previous LoRA weights.")
                except Exception as e:
                    print(f"[HQEngine] Warning on unloading LoRA: {e}")
            return

        lora_path = os.path.join(LORAS_DIR, lora_name)
        if not os.path.exists(lora_path):
            print(f"[HQEngine] LoRA file not found: {lora_path}")
            return

        if self.current_lora != lora_name:
            try:
                if self.current_lora:
                    self.pipe.unload_lora_weights()
                self.pipe.load_lora_weights(lora_path, adapter_name="custom_style")
                self.pipe.set_adapters(["custom_style"], adapter_weights=[float(lora_scale)])
                self.current_lora = lora_name
                print(f"[HQEngine] Applied LoRA '{lora_name}' with scale {lora_scale}")
            except Exception as e:
                print(f"[HQEngine] Failed to apply LoRA '{lora_name}': {e}")
        else:
            try:
                # Just update scale
                self.pipe.set_adapters(["custom_style"], adapter_weights=[float(lora_scale)])
            except Exception:
                pass

    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        enhance_prompt: bool = True,
        lora_name: Optional[str] = None,
        lora_scale: float = 0.8,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        aspect_ratio: str = "1:1",
        seed: Optional[int] = None,
        model_engine=None
    ) -> Dict[str, Any]:
        # Enhance prompt if requested using LLM
        final_prompt = prompt
        enhanced_prompt_text = None
        if enhance_prompt:
            enhanced = self.enhance_prompt_with_llm(prompt, model_engine)
            if enhanced and enhanced != prompt:
                final_prompt = enhanced
                enhanced_prompt_text = enhanced

        # Dynamic VRAM handover: Offload LLM to CPU RAM so SDXL gets 100% full GPU VRAM (fast inference)
        if model_engine is not None and hasattr(model_engine, "offload_to_cpu"):
            model_engine.offload_to_cpu()

        if not self.is_ready:
            success = self.load_model()
            if not success:
                raise RuntimeError(f"Failed to load High-Quality SDXL model: {self.last_error}")

        # Clean CUDA cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Configure LoRA style transfer
        self.apply_lora(lora_name, lora_scale)

        # Resolve Resolution
        res_config = HQ_ASPECT_RATIOS.get(aspect_ratio, HQ_ASPECT_RATIOS["1:1"])
        width = res_config["width"]
        height = res_config["height"]

        # Generator & Seed
        if seed is not None and seed >= 0:
            generator = torch.Generator(device=self.device).manual_seed(seed)
        else:
            seed = int(torch.randint(0, 2**32 - 1, (1,)).item())
            generator = torch.Generator(device=self.device).manual_seed(seed)

        neg_prompt = negative_prompt if negative_prompt and negative_prompt.strip() else DEFAULT_NEGATIVE_PROMPT

        # Clamp steps
        steps = max(15, min(50, int(num_inference_steps)))
        guidance = max(3.0, min(15.0, float(guidance_scale)))

        print(f"[HQEngine] Generating ({width}x{height}, {steps} steps, cfg={guidance}) for: '{final_prompt[:80]}...'")
        start_time = time.time()

        try:
            with torch.inference_mode():
                result = self.pipe(
                    prompt=final_prompt,
                    negative_prompt=neg_prompt,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    generator=generator,
                    width=width,
                    height=height
                )

            elapsed_sec = round(time.time() - start_time, 2)
            image = result.images[0]

            # Convert to Base64
            buffered = io.BytesIO()
            image.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            data_url = f"data:image/png;base64,{img_str}"

            return {
                "image_url": data_url,
                "original_prompt": prompt,
                "final_prompt": final_prompt,
                "enhanced_prompt": enhanced_prompt_text,
                "negative_prompt": neg_prompt,
                "lora_name": lora_name,
                "lora_scale": lora_scale,
                "seed": seed,
                "steps": steps,
                "guidance_scale": guidance,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "elapsed_seconds": elapsed_sec
            }
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if model_engine is not None and hasattr(model_engine, "reload_to_gpu"):
                model_engine.reload_to_gpu()

# Global singleton
hq_image_engine = HighQualityImageEngine()
