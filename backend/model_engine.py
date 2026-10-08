import os
import sys
import threading
import time
from typing import AsyncGenerator, Dict, Any, Optional
import psutil
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

DEFAULT_MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

class LLMEngine:
    def __init__(self, model_id: str = DEFAULT_MODEL_ID):
        self.model_id = model_id
        self.tokenizer = None
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
            print(f"[LLMEngine] Loading model: {self.model_id} on {self.device}...")

            try:
                # Tokenizer loading
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id,
                    trust_remote_code=True
                )

                dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float16
                if not torch.cuda.is_available():
                    dtype = torch.float32

                print(f"[LLMEngine] Using dtype: {dtype}")

                self.model = AutoModelForCausalLM.from_pretrained(
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
                print(f"[LLMEngine] Model {self.model_id} successfully loaded and ready on {self.device}!")
                return True
            except Exception as e:
                self.is_ready = False
                self.is_loading = False
                self.last_error = str(e)
                print(f"[LLMEngine] Error loading model: {e}", file=sys.stderr)
                return False

    def stream_generate(
        self,
        messages: list,
        max_new_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ):
        if not self.is_ready or self.model is None or self.tokenizer is None:
            raise RuntimeError("Model is not loaded. Please wait for model loading or trigger /load.")

        # Prepare chat template
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)

        streamer = TextIteratorStreamer(
            self.tokenizer,
            timeout=60.0,
            skip_prompt=True,
            skip_special_tokens=True
        )

        generate_kwargs = dict(
            **model_inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            temperature=temperature if temperature > 0 else None,
            do_sample=True if temperature > 0 else False,
            top_p=top_p if temperature > 0 else None,
            repetition_penalty=1.1,
            pad_token_id=self.tokenizer.eos_token_id
        )

        # Run generation in a separate thread to allow generator streaming
        thread = threading.Thread(target=self.model.generate, kwargs=generate_kwargs)
        thread.start()

        for new_text in streamer:
            yield new_text

        thread.join()

# Global engine singleton
engine = LLMEngine()
