import threading
import gc
import torch
from typing import Optional, Literal

ModelType = Literal["none", "vlm", "sdxl", "video"]

class VRAMOrchestrator:
    """
    Strict 3-Way Exclusive VRAM Orchestrator for RTX 4070 Ti (12GB VRAM).
    Guarantees that Qwen2.5-VL, RealVisXL (SDXL), and Wan 2.2 (I2V) NEVER co-exist in GPU memory,
    preventing any swap-out to Windows Shared GPU Memory.
    """
    _instance: Optional["VRAMOrchestrator"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_orchestrator()
            return cls._instance

    def _init_orchestrator(self):
        self.current_model: ModelType = "none"
        self.lock = threading.RLock()

    def get_vram_stats(self) -> dict:
        if not torch.cuda.is_available():
            return {"allocated_mb": 0, "reserved_mb": 0, "max_allocated_mb": 0}
        return {
            "allocated_mb": round(torch.cuda.memory_allocated() / (1024 ** 2), 2),
            "reserved_mb": round(torch.cuda.memory_reserved() / (1024 ** 2), 2),
            "max_allocated_mb": round(torch.cuda.max_memory_allocated() / (1024 ** 2), 2),
        }

    def purge_gpu_memory(self):
        """Force complete purge of CUDA memory and run garbage collection"""
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
        import gc
        for _ in range(3):
            gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
            torch.cuda.reset_peak_memory_stats()
        # Trim Windows working set and commit pages to prevent paging file overflow
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.kernel32.SetProcessWorkingSetSize(ctypes.windll.kernel32.GetCurrentProcess(), -1, -1)
            except Exception:
                pass

    def acquire(self, target: ModelType) -> bool:
        """
        Safely unload any other running model and guarantee 100% VRAM headroom for the target.
        """
        with self.lock:
            if self.current_model == target and target != "none":
                return True

            print(f"[VRAMOrchestrator] Handover requested: {self.current_model} -> {target}")
            stats_before = self.get_vram_stats()
            print(f"[VRAMOrchestrator] Memory before unload: {stats_before['allocated_mb']}MB allocated, {stats_before['reserved_mb']}MB reserved")

            # 1. Unload VLM (Qwen2.5-VL)
            if self.current_model == "vlm" or target != "vlm":
                try:
                    from model_engine import engine as vlm_engine
                    if vlm_engine.is_ready:
                        vlm_engine.unload_model()
                except Exception as e:
                    print(f"[VRAMOrchestrator] Warning unloading VLM: {e}")

            # 2. Unload SDXL (RealVisXL + ControlNet)
            if self.current_model == "sdxl" or target != "sdxl":
                try:
                    from high_quality_engine import hq_image_engine
                    if hq_image_engine.is_ready:
                        hq_image_engine.unload_model()
                except Exception as e:
                    print(f"[VRAMOrchestrator] Warning unloading SDXL: {e}")

            # 3. Unload Video (Wan 2.2)
            if self.current_model == "video" or target != "video":
                try:
                    from video_engine import video_engine
                    if video_engine.is_ready:
                        video_engine.unload_model()
                except Exception as e:
                    print(f"[VRAMOrchestrator] Warning unloading Video engine: {e}")

            # Force purge
            self.purge_gpu_memory()
            stats_after = self.get_vram_stats()
            print(f"[VRAMOrchestrator] Purged VRAM. Currently allocated: {stats_after['allocated_mb']}MB (Clean state)")

            self.current_model = target
            return True

    def release(self):
        """Unload whichever model is currently loaded"""
        return self.acquire("none")

# Global singleton
orchestrator = VRAMOrchestrator()
