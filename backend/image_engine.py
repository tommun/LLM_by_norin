import base64
import io
import os
import time
import threading
from typing import Optional, Dict, Any, List
import torch
from diffusers import AutoPipelineForText2Image
from PIL import Image

DEFAULT_IMAGE_MODEL_ID = "stabilityai/sd-turbo"
LORAS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "loras"))

STYLE_PRESETS: Dict[str, Dict[str, str]] = {
    "none": {
        "name": "標準 (Default)",
        "prompt_prefix": "",
        "prompt_suffix": "",
        "negative_prompt": "blurry, low quality, distorted"
    },
    "anime": {
        "name": "アニメ調 (Anime / Manga)",
        "prompt_prefix": "masterpiece, best quality, vibrant anime aesthetic, crisp lineart, Studio Ghibli and Makoto Shinkai style, ",
        "prompt_suffix": ", beautiful anime coloring, highly detailed eyes and hair",
        "negative_prompt": "photorealistic, realistic, 3d render, blurry, low quality, deformed"
    },
    "photorealistic": {
        "name": "写実・写真 (Photorealistic)",
        "prompt_prefix": "photorealistic, 8k resolution, raw photo, realistic textures, natural lighting, shot on 35mm lens, ",
        "prompt_suffix": ", highly detailed skin texture, award winning photography",
        "negative_prompt": "anime, cartoon, drawing, illustration, blurry, bad anatomy"
    },
    "watercolor": {
        "name": "水彩画 (Watercolor)",
        "prompt_prefix": "delicate watercolor painting, soft color wash, paper texture, fluid gradients, expressive brush strokes, ",
        "prompt_suffix": ", artistic watercolor aesthetic, splashed paint accents",
        "negative_prompt": "photorealistic, 3d render, harsh lines, plastic"
    },
    "oil": {
        "name": "油絵 (Oil Painting)",
        "prompt_prefix": "classic oil painting on canvas, thick impasto brushstrokes, rich textural details, museum masterpiece, ",
        "prompt_suffix": ", dramatic chiaroscuro lighting, fine art masterpiece",
        "negative_prompt": "anime, 3d render, flat digital art, low quality"
    },
    "cyberpunk": {
        "name": "サイバーパンク (Cyberpunk)",
        "prompt_prefix": "cyberpunk style, glowing neon lights, futuristic high-tech metropolis, neon reflections, rainy aesthetic, ",
        "prompt_suffix": ", volumetric lighting, blade runner vibe, 8k resolution",
        "negative_prompt": "pastoral, medieval, fantasy, sunny day, low quality"
    },
    "pixel": {
        "name": "ピクセルアート (Pixel Art)",
        "prompt_prefix": "detailed 16-bit pixel art, retro gaming aesthetic, vibrant pixel palette, clean sprite, ",
        "prompt_suffix": ", nostalgic arcade game graphics",
        "negative_prompt": "smooth, vector, photorealistic, blurry, high poly 3d"
    },
    "3d": {
        "name": "3Dデジタル (3D Render)",
        "prompt_prefix": "octane render, unreal engine 5, raytracing reflections, 3D digital sculpture, cinematic lighting, ",
        "prompt_suffix": ", smooth surfaces, subsurface scattering, 8k wallpaper",
        "negative_prompt": "flat 2d, sketch, rough drawing, low quality"
    }
}

class ImageGenEngine:
    def __init__(self, model_id: str = DEFAULT_IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error = None
        self.current_lora = None
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
            print(f"[ImageGenEngine] Loading image model: {self.model_id} on {self.device}...")

            try:
                dtype = torch.float16 if torch.cuda.is_available() else torch.float32
                self.pipe = AutoPipelineForText2Image.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    variant="fp16" if torch.cuda.is_available() else None
                )

                if torch.cuda.is_available():
                    self.pipe = self.pipe.to(self.device)

                self.is_ready = True
                self.is_loading = False
                print(f"[ImageGenEngine] Image model {self.model_id} successfully loaded and ready!")
                return True
            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                print(f"[ImageGenEngine] Error loading model: {e}")
                return False

    def apply_lora(self, lora_name: Optional[str], lora_weight: float = 1.0):
        if not lora_name:
            if self.current_lora and hasattr(self.pipe, "unload_lora_weights"):
                try:
                    self.pipe.unload_lora_weights()
                    self.current_lora = None
                except Exception:
                    pass
            return

        lora_path = os.path.join(LORAS_DIR, lora_name)
        if not os.path.exists(lora_path):
            return

        if self.current_lora != lora_name:
            try:
                if self.current_lora and hasattr(self.pipe, "unload_lora_weights"):
                    self.pipe.unload_lora_weights()
                self.pipe.load_lora_weights(lora_path)
                self.current_lora = lora_name
                print(f"[ImageGenEngine] Loaded LoRA: {lora_name}")
            except Exception as e:
                print(f"[ImageGenEngine] Failed to load LoRA {lora_name}: {e}")

    def generate(
        self,
        prompt: str,
        style: str = "none",
        lora_name: Optional[str] = None,
        lora_weight: float = 1.0,
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        seed: Optional[int] = None,
        width: int = 512,
        height: int = 512
    ) -> Dict[str, Any]:
        if not self.is_ready:
            success = self.load_model()
            if not success:
                raise RuntimeError(f"Failed to load image model: {self.last_error}")

        # Handle LoRA
        self.apply_lora(lora_name, lora_weight)

        # Style preset prompt injection
        preset = STYLE_PRESETS.get(style, STYLE_PRESETS["none"])
        styled_prompt = f"{preset['prompt_prefix']}{prompt}{preset['prompt_suffix']}"

        # Ensure width and height are divisible by 8 and clamped safely
        safe_width = max(256, min(768, (int(width) // 8) * 8))
        safe_height = max(256, min(768, (int(height) // 8) * 8))

        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator(device=self.device).manual_seed(seed)
        else:
            seed = int(torch.randint(0, 2**32 - 1, (1,)).item())
            generator = torch.Generator(device=self.device).manual_seed(seed)

        start_time = time.time()
        with torch.inference_mode():
            result = self.pipe(
                prompt=styled_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
                width=safe_width,
                height=safe_height
            )

        elapsed_sec = round(time.time() - start_time, 2)
        image = result.images[0]

        # Convert PIL image to base64
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        data_url = f"data:image/png;base64,{img_str}"

        return {
            "image_url": data_url,
            "prompt": prompt,
            "styled_prompt": styled_prompt,
            "style": style,
            "style_name": preset["name"],
            "seed": seed,
            "steps": num_inference_steps,
            "width": safe_width,
            "height": safe_height,
            "elapsed_seconds": elapsed_sec,
            "model_id": self.model_id
        }

# Global image engine singleton
image_engine = ImageGenEngine()
