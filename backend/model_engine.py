import os
import sys
import threading
import time
from typing import AsyncGenerator, Dict, Any, Optional, List
import psutil
import torch
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, TextIteratorStreamer
from qwen_vl_utils import process_vision_info

DEFAULT_MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct"

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
            "is_loading": self.is_loading,
        }

        if torch.cuda.is_available():
            try:
                device_idx = 0
                props = torch.cuda.get_device_properties(device_idx)
                allocated = torch.cuda.memory_allocated(device_idx)
                reserved = torch.cuda.memory_reserved(device_idx)
                info["device_name"] = props.name
                info["vram_total_mb"] = round(props.total_memory / (1024 * 1024), 1)
                info["vram_used_mb"] = round(allocated / (1024 * 1024), 1)
                info["vram_reserved_mb"] = round(reserved / (1024 * 1024), 1)
                info["vram_percent"] = round((reserved / props.total_memory) * 100, 1)
            except Exception as e:
                info["gpu_query_error"] = str(e)
        return info

    def load_model(self, model_id: Optional[str] = None) -> bool:
        with self.load_lock:
            if model_id:
                self.model_id = model_id

            self.is_loading = True
            self.last_error = None
            print(f"[LLMEngine] Loading Vision-Language Model: {self.model_id} on {self.device}...")

            try:
                # Processor loading (Tokenizer + Image Processor)
                self.processor = AutoProcessor.from_pretrained(
                    self.model_id,
                    trust_remote_code=True
                )

                dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float16
                if not torch.cuda.is_available():
                    dtype = torch.float32

                print(f"[LLMEngine] Using dtype: {dtype}")

                self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    device_map="auto" if torch.cuda.is_available() else None,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )

                if not torch.cuda.is_available():
                    self.model = self.model.to("cpu")

                self.model.eval()
                self.is_ready = True
                self.is_loading = False
                print(f"[LLMEngine] Vision Model {self.model_id} successfully loaded and ready on {self.device}!")
                return True
            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                print(f"[LLMEngine] Error loading vision model: {e}", file=sys.stderr)
                return False

    def stream_generate(
        self,
        messages: list,
        max_new_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ):
        if not self.is_ready or self.model is None or self.processor is None:
            raise RuntimeError("Vision Model is not loaded. Please wait for model loading.")

        # Transform messages into multimodal format
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content_list = []

            # If message contains images
            images = msg.get("images", [])
            for img_url in images:
                content_list.append({"type": "image", "image": img_url})

            # Text content
            text_str = msg.get("content", "")
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
            timeout=60.0,
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

        thread = threading.Thread(target=self.model.generate, kwargs=generate_kwargs)
        thread.start()

        for new_text in streamer:
            yield new_text

        thread.join()

# Global engine singleton
engine = LLMEngine()
