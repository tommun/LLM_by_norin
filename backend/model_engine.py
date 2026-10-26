import os
import sys
import threading
import time
from typing import AsyncGenerator, Dict, Any, Optional, List
import psutil
import torch
from transformers import AutoProcessor, TextIteratorStreamer, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from tagger_engine import tagger

# Try importing Qwen2.5-VL model class, fallback to Qwen2-VL or AutoModel
try:
    from transformers import Qwen2_5_VLForConditionalGeneration as VisionModelClass
except ImportError:
    try:
        from transformers import Qwen2VLForConditionalGeneration as VisionModelClass
    except ImportError:
        from transformers import AutoModelForVision2Seq as VisionModelClass

# Abliterated (Uncensored) or Standard Vision-Language Model
DEFAULT_MODEL_ID = os.getenv("VISION_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct")
FALLBACK_MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

class LLMEngine:
    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        self.model_id = model_id
        self.processor = None
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loading = False
        self.is_ready = False
        self.last_error = None
        self.load_lock = threading.Lock()

    def get_gpu_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "cuda_available": torch.cuda.is_available(),
            "device": self.device,
            "device_name": "CPU",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_reserved_mb": 0,
            "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 1),
            "ram_used_mb": round(psutil.virtual_memory().used / (1024 * 1024), 1),
            "ram_percent": psutil.virtual_memory().percent,
            "model_id": self.model_id,
            "model_loaded": self.is_ready,
            "is_loading": self.is_loading
        }
        if torch.cuda.is_available():
            try:
                info["device_name"] = torch.cuda.get_device_name(0)
                info["vram_total_mb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024), 1)
                info["vram_used_mb"] = round(torch.cuda.memory_allocated(0) / (1024 * 1024), 1)
                info["vram_reserved_mb"] = round(torch.cuda.memory_reserved(0) / (1024 * 1024), 1)
                info["vram_percent"] = round((info["vram_used_mb"] / info["vram_total_mb"]) * 100, 1)
            except Exception as e:
                info["gpu_query_error"] = str(e)
        return info

    def load_model(self, model_id: Optional[str] = None) -> bool:
        with self.load_lock:
            if model_id:
                self.model_id = model_id

            self.is_loading = True
            self.last_error = None

            # Free VRAM: ensure SDXL is completely unloaded before loading Vision LLM
            try:
                from high_quality_engine import hq_image_engine
                if hq_image_engine.is_ready:
                    hq_image_engine.unload_model()
            except Exception as ex:
                print(f"[LLMEngine] Warning unloading SDXL: {ex}")

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                import gc
                gc.collect()

            print(f"[LLMEngine] Loading Vision-Language Model: {self.model_id} (4-bit NF4 quantized) on {self.device}...")

            # Attempt loading target model, fallback to FALLBACK_MODEL_ID if target snapshot unavailable
            candidate_models = [self.model_id]
            if self.model_id != FALLBACK_MODEL_ID:
                candidate_models.append(FALLBACK_MODEL_ID)

            loaded_successfully = False
            for cand_id in candidate_models:
                try:
                    min_pixels = 256 * 28 * 28
                    max_pixels = 512 * 28 * 28
                    self.processor = AutoProcessor.from_pretrained(
                        cand_id,
                        min_pixels=min_pixels,
                        max_pixels=max_pixels,
                        trust_remote_code=True
                    )

                    if torch.cuda.is_available():
                        print(f"[LLMEngine] Applying 4-bit NF4 quantization for {cand_id}...")
                        bnb_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_compute_dtype=torch.bfloat16,
                            bnb_4bit_use_double_quant=True,
                        )
                        self.model = VisionModelClass.from_pretrained(
                            cand_id,
                            quantization_config=bnb_config,
                            device_map="auto",
                            trust_remote_code=True,
                            low_cpu_mem_usage=True
                        )
                    else:
                        self.model = VisionModelClass.from_pretrained(
                            cand_id,
                            torch_dtype=torch.float32,
                            trust_remote_code=True,
                            low_cpu_mem_usage=True
                        ).to("cpu")

                    self.model.eval()
                    self.model_id = cand_id
                    self.is_ready = True
                    self.is_loading = False
                    loaded_successfully = True
                    print(f"[LLMEngine] Vision Model {self.model_id} successfully loaded and ready on {self.device}!")
                    break
                except Exception as e:
                    print(f"[LLMEngine] Failed loading {cand_id}: {e}", file=sys.stderr)
                    self.last_error = str(e)

            if not loaded_successfully:
                self.is_ready = False
                self.is_loading = False
                return False

            # Warm up WD14 Tagger engine
            try:
                tagger.load_model()
            except Exception as te:
                print(f"[LLMEngine] Tagger pre-load warning: {te}")

            return True

    def unload_model(self):
        """Completely unload Vision LLM from GPU memory to grant 100% VRAM to SDXL"""
        with self.load_lock:
            if self.model is not None or self.processor is not None:
                print("[LLMEngine] Unloading Vision LLM from GPU to free full VRAM...")
                del self.model
                del self.processor
                self.model = None
                self.processor = None
                self.is_ready = False
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print("[LLMEngine] Vision LLM unloaded. GPU VRAM completely freed.")

    def stream_generate(
        self,
        messages: list,
        max_new_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ):
        if not self.is_ready or self.model is None or self.processor is None:
            print("[LLMEngine] Model not currently in memory. Loading on demand...")
            success = self.load_model()
            if not success or self.model is None or self.processor is None:
                raise RuntimeError(f"Vision Model failed to load: {self.last_error}")

        # Transform messages into multimodal format
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content_list = []

            # If message contains images, also extract Danbooru tags via WD14 Tagger
            images = msg.get("images", [])
            extracted_tags_info = []
            for img_url in images:
                content_list.append({
                    "type": "image",
                    "image": img_url,
                    "min_pixels": 256 * 28 * 28,
                    "max_pixels": 512 * 28 * 28
                })
                try:
                    tag_res = tagger.extract_tags(img_url, general_threshold=0.25)
                    if tag_res and tag_res.get("tags"):
                        top_tags = tag_res["tags"][:30]
                        extracted_tags_info.append(f"WD14 Danbooru Tags (Rating: {tag_res.get('rating')}): {', '.join(top_tags)}")
                except Exception as te:
                    print(f"[LLMEngine] Tagger extraction note: {te}", flush=True)

            # Text content
            text_str = msg.get("content", "")
            if extracted_tags_info:
                tags_formatted = "\n".join(extracted_tags_info)
                text_str = (
                    f"{text_str}\n\n"
                    f"【WD14 Tagger画像解析タグ（Danbooru/Gelbooru形式）】:\n{tags_formatted}\n"
                    f"※指示: 上記の正確なタグ情報および画像のポーズ・構図・アングルを完璧に反映し、最高峰の英語プロンプトを出力してください。"
                )

            if text_str:
                content_list.append({"type": "text", "text": text_str})

            # If neither image nor text, skip or provide empty text
            if not content_list:
                content_list.append({"type": "text", "text": ""})

            formatted_messages.append({"role": role, "content": content_list})

        # Apply chat template
        text = self.processor.apply_chat_template(
            formatted_messages,
            tokenize=False,
            add_generation_prompt=True
        )

        image_inputs, video_inputs = process_vision_info(formatted_messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt"
        ).to(self.device)

        streamer = TextIteratorStreamer(
            self.processor.tokenizer,
            timeout=120.0,
            skip_prompt=True,
            skip_special_tokens=True
        )

        generate_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            temperature=temperature if temperature > 0 else None,
            do_sample=True if temperature > 0 else False,
            top_p=top_p if temperature > 0 else None,
            repetition_penalty=1.1,
            pad_token_id=self.processor.tokenizer.eos_token_id
        )

        generation_error: List[Exception] = []

        def _generate_worker():
            try:
                self.model.generate(**generate_kwargs)
            except Exception as e:
                generation_error.append(e)
                import traceback
                print(f"[LLMEngine] Exception in generate worker: {e}", file=sys.stderr)
                traceback.print_exc()
                try:
                    streamer.end()
                except Exception:
                    pass

        thread = threading.Thread(target=_generate_worker)
        thread.start()

        for new_text in streamer:
            yield new_text

        thread.join()

        if generation_error:
            raise generation_error[0]

# Global engine singleton
engine = LLMEngine()
