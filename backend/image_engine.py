import base64
import io
import time
import threading
from typing import Optional, Dict, Any
import torch
from diffusers import AutoPipelineForText2Image
from PIL import Image

DEFAULT_IMAGE_MODEL_ID = "stabilityai/sd-turbo"

class ImageGenEngine:
    def __init__(self, model_id: str = DEFAULT_IMAGE_MODEL_ID):
        self.model_id = model_id
        self.pipe = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error = None
        self.lock = threading.Lock()

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

    def generate(
        self,
        prompt: str,
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
                prompt=prompt,
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
            "seed": seed,
            "steps": num_inference_steps,
            "width": safe_width,
            "height": safe_height,
            "elapsed_seconds": elapsed_sec,
            "model_id": self.model_id
        }

# Global image engine singleton
image_engine = ImageGenEngine()
