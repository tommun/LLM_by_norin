import base64
import io
import os
import time
import threading
from typing import Optional, Dict, Any, List
import torch
from diffusers import (
    StableDiffusionXLPipeline,
    StableDiffusionXLControlNetPipeline,
    StableDiffusionXLImg2ImgPipeline,
    AutoPipelineForImage2Image,
    ControlNetModel,
    DPMSolverMultistepScheduler
)
from PIL import Image
from openpose_engine import pose_extractor

DEFAULT_HQ_MODEL_ID = os.getenv("SDXL_MODEL_ID", "SG161222/RealVisXL_V4.0")
LORAS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "loras"))
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "models"))
CONTROLNET_PATH = os.path.join(MODELS_DIR, "OpenPoseXL2.safetensors")
CONTROLNET_CONFIG = os.path.join(MODELS_DIR, "controlnet_config.json")
os.makedirs(LORAS_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# Recommended resolutions for SDXL (divisible by 64 or 8)
HQ_ASPECT_RATIOS = {
    "1:1": {"width": 1024, "height": 1024, "label": "正方形 (1024×1024)"},
    "16:9": {"width": 1216, "height": 832, "label": "シネマ横長 (1216×832)"},
    "9:16": {"width": 832, "height": 1216, "label": "スマホ縦長 (832×1216)"},
    "4:3": {"width": 1152, "height": 896, "label": "写真横長 (1152×896)"},
    "3:4": {"width": 896, "height": 1152, "label": "ポスター縦長 (896×1152)"},
}

DEFAULT_NEGATIVE_PROMPT = (
    "(deformed iris, deformed pupils, semi-realistic, cgi, 3d, render, sketch, cartoon, drawing, anime:1.4), "
    "ugly, deformed, noisy, blurry, low contrast, distorted anatomy, extra limbs, "
    "bad hands, missing fingers, poorly drawn face, mutated, disfigured, watermark, "
    "signature, text, low quality, artifacts, child, loli, teen, young, underage, school uniform"
)

class HighQualityImageEngine:
    """
    High-Quality SDXL Engine designed for RTX 4070 Ti (12GB VRAM).
    Focuses on maximum prompt fidelity, intricate details, and custom style LoRA transfer.
    """
    def __init__(self, model_id: str = DEFAULT_HQ_MODEL_ID):
        self.model_id = model_id
        self.pipe: Optional[StableDiffusionXLPipeline] = None
        self.img2img_pipe: Optional[Any] = None
        self.controlnet: Optional[ControlNetModel] = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error: Optional[str] = None
        self.current_lora: Optional[str] = None
        self.lock = threading.Lock()

    def load_controlnet(self) -> Optional[ControlNetModel]:
        """Load OpenPoseXL2 ControlNet model (approx 2.5GB in fp16)"""
        if self.controlnet is not None:
            return self.controlnet
        if not os.path.exists(CONTROLNET_PATH):
            print(f"[HQEngine] ControlNet model not found at {CONTROLNET_PATH}")
            return None
        print(f"[HQEngine] Loading OpenPoseXL2 ControlNet from {CONTROLNET_PATH}...")
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        try:
            self.controlnet = ControlNetModel.from_single_file(
                CONTROLNET_PATH,
                config=CONTROLNET_CONFIG if os.path.exists(CONTROLNET_CONFIG) else None,
                torch_dtype=dtype
            )
            if torch.cuda.is_available():
                self.controlnet = self.controlnet.to("cuda")
            print("[HQEngine] OpenPoseXL2 ControlNet loaded successfully!")
            return self.controlnet
        except Exception as e:
            print(f"[HQEngine] Failed to load ControlNet: {e}")
            return None

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
                # Orchestrator handover
                try:
                    from vram_orchestrator import orchestrator
                    orchestrator.acquire("sdxl")
                except Exception as oe:
                    print(f"[HQEngine] Orchestrator notice: {oe}")

                # Clean CUDA cache before loading
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                try:
                    self.pipe = StableDiffusionXLPipeline.from_pretrained(
                        self.model_id,
                        torch_dtype=dtype,
                        variant="fp16" if torch.cuda.is_available() else None,
                        use_safetensors=True
                    )
                except Exception as e:
                    print(f"[HQEngine] Loading with variant='fp16' failed ({e}), retrying without variant...")
                    self.pipe = StableDiffusionXLPipeline.from_pretrained(
                        self.model_id,
                        torch_dtype=dtype,
                        use_safetensors=True
                    )

                # Set DPM++ 2M Karras Scheduler for clean, artful textures
                self.pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                    self.pipe.scheduler.config,
                    use_karras_sigmas=True,
                    algorithm_type="dpmsolver++"
                )

                # Enable TensorCore TF32 & CuDNN benchmark for maximum speed on RTX 4070 Ti
                if torch.cuda.is_available():
                    torch.backends.cuda.matmul.allow_tf32 = True
                    torch.backends.cudnn.allow_tf32 = True
                    torch.backends.cudnn.benchmark = True

                    self.pipe = self.pipe.to("cuda")

                    # Apply channels_last memory format for 20-30% faster UNet inference on Ada Lovelace
                    try:
                        self.pipe.unet.to(memory_format=torch.channels_last)
                    except Exception:
                        pass

                    if hasattr(self.pipe, "vae") and self.pipe.vae is not None:
                        try:
                            self.pipe.vae.to(dtype=torch.float32)
                        except Exception:
                            pass
                        if hasattr(self.pipe.vae, "enable_tiling"):
                            self.pipe.vae.enable_tiling()
                        if hasattr(self.pipe.vae, "enable_slicing"):
                            self.pipe.vae.enable_slicing()

                    # Pre-cache img2img pipeline with zero memory duplication
                    try:
                        self.img2img_pipe = AutoPipelineForImage2Image.from_pipe(self.pipe)
                    except Exception:
                        self.img2img_pipe = None

                self.is_ready = True
                self.is_loading = False
                print(f"[HQEngine] SDXL {self.model_id} successfully loaded in CUDA VRAM for high-speed generation!")
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
            "You are a world-class prompt engineer for Midjourney v6 and SDXL specializing in fine-art aesthetics and photographic realism. "
            "Transform the user's concept into an elaborate, masterfully composed English prompt. "
            "CRITICAL RULES: "
            "1. NEVER contradict, remove, or neutralize the user's specific instructions. "
            "2. If the user specifies attire, clothing, nudity, or exposure level (e.g. topless, bare breasts, bare skin, micro bikini, string bikini, cutout swimsuit), you MUST preserve and faithfully expand upon those exact elements. NEVER add unwanted clothing, sportswear, or modesty garments that contradict the user's intent. "
            "3. For artistic figure, fitness, and beauty depictions, employ sophisticated fine-art vocabulary: dramatic chiaroscuro, Venetian blind shadows, golden hour rim lighting, silhouette contour, sculpted muscular anatomy, photorealistic glistening skin texture, 35mm raw photography. "
            "4. Ensure the sentence is complete and never cut off mid-sentence. "
            "5. Output ONLY the English prompt without any preamble, quotes, or markdown."
        )

        try:
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Concept: {user_prompt}"}
            ]
            tokens = []
            for token in model_engine.stream_generate(
                messages=messages,
                max_new_tokens=350,
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
        pose_image: Optional[str] = None,
        controlnet_scale: float = 0.85,
        init_image: Optional[str] = None,
        denoise_strength: float = 0.60,
        model_engine=None
    ) -> Dict[str, Any]:
        # Enhance prompt if requested using LLM
        final_prompt = prompt
        enhanced_prompt_text = None
        if enhance_prompt:
            # If prompt already looks like an advanced masterpiece prompt from Prompt Craftsman, skip redundant re-enhancement to preserve user's exact adjustments
            prompt_lower = prompt.lower()
            is_already_elaborate = (
                len(prompt.split()) > 25 and (
                    "masterpiece" in prompt_lower or "8k" in prompt_lower or "photorealistic" in prompt_lower or "ultra-detailed" in prompt_lower
                )
            )
            if not is_already_elaborate:
                enhanced = self.enhance_prompt_with_llm(prompt, model_engine)
                if enhanced and enhanced != prompt:
                    final_prompt = enhanced
                    enhanced_prompt_text = enhanced

        # Trigger word injection for trained LoRA (Ensures style is triggered strongly)
        if lora_name:
            style_trigger = os.path.splitext(lora_name)[0]
            if style_trigger and style_trigger.lower() not in final_prompt.lower():
                final_prompt = f"{final_prompt}, in style of {style_trigger}"

        # Dynamic VRAM handover: Unload Vision LLM so SDXL gets 100% full GPU VRAM (fast inference)
        if model_engine is not None and hasattr(model_engine, "unload_model"):
            model_engine.unload_model()

        if not self.is_ready:
            success = self.load_model()
            if not success:
                raise RuntimeError(f"Failed to load High-Quality SDXL model: {self.last_error}")

        # Clean CUDA cache and force garbage collection to keep dedicated VRAM unfragmented
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass

        # Configure LoRA style transfer
        self.apply_lora(lora_name, lora_scale)

        # Resolve Resolution
        res_config = HQ_ASPECT_RATIOS.get(aspect_ratio, HQ_ASPECT_RATIOS["1:1"])
        width = res_config["width"]
        height = res_config["height"]

        # Decode init_image for img2img remake if provided
        init_image_pil = None
        if init_image:
            try:
                raw_init_str = init_image
                if "," in raw_init_str:
                    raw_init_str = raw_init_str.split(",", 1)[1]
                init_bytes = base64.b64decode(raw_init_str)
                raw_pil = Image.open(io.BytesIO(init_bytes)).convert("RGB")
                
                # If aspect ratio wasn't explicitly changed from 1:1 default, match original image aspect
                orig_w, orig_h = raw_pil.size
                if aspect_ratio == "1:1" and orig_h > orig_w * 1.15:
                    width, height = 832, 1216  # 9:16 portrait
                    aspect_ratio = "9:16"
                elif aspect_ratio == "1:1" and orig_w > orig_h * 1.15:
                    width, height = 1216, 832  # 16:9 landscape
                    aspect_ratio = "16:9"

                init_image_pil = raw_pil.resize((width, height), Image.Resampling.LANCZOS)
                print(f"[HQEngine] Loaded init_image for img2img remake: resized to ({width}x{height}), denoise_strength={denoise_strength}")
            except Exception as e:
                print(f"[HQEngine] Warning: Failed to process init_image: {e}. Falling back to txt2img.")
                init_image_pil = None

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

        # Process pose image for ControlNet OpenPose if provided
        control_image = None
        pose_skeleton_data_url = None
        if pose_image:
            try:
                print("[HQEngine] Processing pose reference image for OpenPose ControlNet...")
                raw_pose_str = pose_image
                if "," in raw_pose_str:
                    raw_pose_str = raw_pose_str.split(",", 1)[1]
                pose_bytes = base64.b64decode(raw_pose_str)
                input_pil = Image.open(io.BytesIO(pose_bytes)).convert("RGB")
                
                # Extract OpenPose wireframe skeleton
                skeleton_pil = pose_extractor.extract_pose(input_pil, include_hand_and_face=True)
                # Resize skeleton to target generation dimensions
                control_image = skeleton_pil.resize((width, height), Image.Resampling.LANCZOS)

                # Save skeleton DataURL for client feedback
                skel_buf = io.BytesIO()
                skeleton_pil.save(skel_buf, format="PNG")
                pose_skeleton_data_url = f"data:image/png;base64,{base64.b64encode(skel_buf.getvalue()).decode('utf-8')}"
                print("[HQEngine] Skeleton extracted successfully!")
            except Exception as e:
                print(f"[HQEngine] Warning: Failed to extract pose: {e}. Falling back to standard generation.")
                control_image = None

        is_img2img = init_image_pil is not None
        print(f"[HQEngine] Generating ({width}x{height}, {steps} steps, cfg={guidance}, img2img={'ON (' + str(denoise_strength) + ')' if is_img2img else 'OFF'}, controlnet={'ON' if control_image else 'OFF'}) for: '{final_prompt[:80]}...'")
        start_time = time.time()

        try:
            with torch.inference_mode():
                if is_img2img:
                    # Fast Zero-Copy Img2Img Pipeline sharing weights directly on CUDA
                    if not self.img2img_pipe:
                        self.img2img_pipe = AutoPipelineForImage2Image.from_pipe(self.pipe)

                    clamped_strength = max(0.1, min(1.0, float(denoise_strength)))
                    result = self.img2img_pipe(
                        prompt=final_prompt,
                        negative_prompt=neg_prompt,
                        image=init_image_pil,
                        strength=clamped_strength,
                        num_inference_steps=steps,
                        guidance_scale=guidance,
                        generator=generator
                    )
                elif control_image is not None:
                    cnet = self.load_controlnet()
                    if cnet is not None:
                        # Construct ephemeral ControlNet pipeline sharing self.pipe weights
                        cnet_pipe = StableDiffusionXLControlNetPipeline(
                            vae=self.pipe.vae,
                            text_encoder=self.pipe.text_encoder,
                            text_encoder_2=self.pipe.text_encoder_2,
                            tokenizer=self.pipe.tokenizer,
                            tokenizer_2=self.pipe.tokenizer_2,
                            unet=self.pipe.unet,
                            scheduler=self.pipe.scheduler,
                            controlnet=cnet
                        )
                        result = cnet_pipe(
                            prompt=final_prompt,
                            negative_prompt=neg_prompt,
                            image=control_image,
                            controlnet_conditioning_scale=float(controlnet_scale),
                            num_inference_steps=steps,
                            guidance_scale=guidance,
                            generator=generator,
                            width=width,
                            height=height
                        )
                        del cnet_pipe
                    else:
                        result = self.pipe(
                            prompt=final_prompt,
                            negative_prompt=neg_prompt,
                            num_inference_steps=steps,
                            guidance_scale=guidance,
                            generator=generator,
                            width=width,
                            height=height
                        )
                else:
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
                "pose_skeleton_url": pose_skeleton_data_url,
                "original_prompt": prompt,
                "final_prompt": final_prompt,
                "enhanced_prompt": enhanced_prompt_text,
                "negative_prompt": neg_prompt,
                "lora_name": lora_name,
                "lora_scale": lora_scale,
                "img2img_active": is_img2img,
                "denoise_strength": denoise_strength if is_img2img else None,
                "controlnet_active": control_image is not None,
                "controlnet_scale": controlnet_scale if control_image is not None else None,
                "seed": seed,
                "steps": steps,
                "guidance_scale": guidance,
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "elapsed_seconds": elapsed_sec
            }
        finally:
            # Offload SDXL to CPU RAM to immediately free 6.5GB VRAM for Vision LLM
            self.offload_to_cpu()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def unload_model(self):
        """Unload SDXL and ControlNet from GPU to free full VRAM for Vision LLM"""
        with self.lock:
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass
            if self.img2img_pipe is not None:
                del self.img2img_pipe
                self.img2img_pipe = None
            if self.pipe is not None:
                print("[HQEngine] Unloading SDXL from GPU to free full VRAM...")
                del self.pipe
                self.pipe = None
            if self.controlnet is not None:
                print("[HQEngine] Unloading ControlNet from GPU...")
                del self.controlnet
                self.controlnet = None
            self.is_ready = False
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print("[HQEngine] All image generation models unloaded. GPU VRAM completely freed.")

    def offload_to_cpu(self):
        """Clean CUDA cache"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def reload_to_gpu(self):
        """Clean CUDA cache"""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

# Global singleton
hq_image_engine = HighQualityImageEngine()
