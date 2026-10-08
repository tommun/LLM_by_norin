"""
Local Art Style LoRA Training Module for RTX 4070 Ti (12GB VRAM).
Optimized with cached Latents & Text Embeddings for ultra-fast training (1-2 mins).
"""

import os
import gc
import glob
import time
import threading
from typing import Optional, Callable, Dict, Any, List
from PIL import Image

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms

from diffusers import AutoencoderKL, UNet2DConditionModel, DDPMScheduler
from transformers import CLIPTokenizer, CLIPTextModel
from peft import LoraConfig, get_peft_model


# Training progress global tracker
class TrainingTracker:
    def __init__(self):
        self.is_training = False
        self.should_stop = False
        self.style_name = ""
        self.current_step = 0
        self.total_steps = 0
        self.progress_percent = 0.0
        self.current_loss = 0.0
        self.start_time = 0.0
        self.elapsed_seconds = 0.0
        self.estimated_remaining_seconds = 0.0
        self.status_message = "Idle"
        self.error_message: Optional[str] = None
        self.saved_lora_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_training": self.is_training,
            "style_name": self.style_name,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "progress_percent": round(self.progress_percent, 1),
            "current_loss": round(self.current_loss, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "estimated_remaining_seconds": round(self.estimated_remaining_seconds, 1),
            "status_message": self.status_message,
            "error_message": self.error_message,
            "saved_lora_path": self.saved_lora_path,
        }

tracker = TrainingTracker()


class StyleDataset(Dataset):
    def __init__(self, image_paths: List[str], captions: List[str], size: int = 512):
        self.image_paths = image_paths
        self.captions = captions
        self.transform = transforms.Compose([
            transforms.Resize((size, size), interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.ToTensor(),
            transforms.Normalize([0.5], [0.5]),
        ])

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        path = self.image_paths[idx]
        caption = self.captions[idx]
        image = Image.open(path).convert("RGB")
        pixel_values = self.transform(image)
        return {"pixel_values": pixel_values, "caption": caption}


def auto_caption_image(image_path: str, style_name: str, vision_model, vision_processor) -> str:
    """Use Qwen2-VL to automatically describe the image subject without mentioning style."""
    if vision_model is None or vision_processor is None:
        return f"a photo in style of {style_name}"
    
    try:
        from qwen_vl_utils import process_vision_info
        img = Image.open(image_path).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": "Describe the main subject and composition of this image concisely in English (one sentence, do not describe the artistic style)."},
                ],
            }
        ]
        text_prompt = vision_processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = vision_processor(
            text=[text_prompt],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to("cuda")
        
        with torch.no_grad():
            generated_ids = vision_model.generate(**inputs, max_new_tokens=50)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            caption = vision_processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0].strip()
        
        return f"{caption}, in style of {style_name}"
    except Exception as e:
        print(f"[AutoCaption] Warning: captioning failed for {image_path}: {e}")
        return f"artwork of a subject, in style of {style_name}"


def run_lora_training(
    dataset_dir: str,
    style_name: str,
    output_dir: str = "loras",
    model_id: str = "stabilityai/sd-turbo",
    total_steps: int = 400,
    learning_rate: float = 1e-4,
    lora_rank: int = 8,
    batch_size: int = 1,
    auto_caption: bool = True,
    vision_engine = None,
):
    """
    Train a LoRA model on a directory of style images and save as .safetensors.
    """
    global tracker
    tracker.is_training = True
    tracker.should_stop = False
    tracker.style_name = style_name
    tracker.current_step = 0
    tracker.total_steps = total_steps
    tracker.progress_percent = 0.0
    tracker.current_loss = 0.0
    tracker.start_time = time.time()
    tracker.status_message = "Preparing dataset..."
    tracker.error_message = None
    tracker.saved_lora_path = None

    os.makedirs(output_dir, exist_ok=True)
    out_safetensors_path = os.path.join(output_dir, f"{style_name}.safetensors")

    try:
        # 1. Discover images
        valid_extensions = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp")
        image_paths = []
        for ext in valid_extensions:
            image_paths.extend(glob.glob(os.path.join(dataset_dir, ext)))
            image_paths.extend(glob.glob(os.path.join(dataset_dir, ext.upper())))
        
        if not image_paths:
            raise ValueError(f"No valid images found in dataset directory: {dataset_dir}")

        tracker.status_message = f"Found {len(image_paths)} images. Preparing captions..."
        print(f"[LoRA Training] Found {len(image_paths)} images for style '{style_name}'.")

        # 2. Prepare captions
        captions = []
        v_model = getattr(vision_engine, "model", None) if vision_engine else None
        v_proc = getattr(vision_engine, "processor", None) if vision_engine else None

        for idx, img_path in enumerate(image_paths):
            txt_path = os.path.splitext(img_path)[0] + ".txt"
            if os.path.exists(txt_path):
                with open(txt_path, "r", encoding="utf-8") as f:
                    cap = f.read().strip()
                if f"style of {style_name}" not in cap:
                    cap = f"{cap}, in style of {style_name}"
            elif auto_caption and v_model is not None and v_proc is not None:
                tracker.status_message = f"Generating AI caption for image {idx+1}/{len(image_paths)}..."
                cap = auto_caption_image(img_path, style_name, v_model, v_proc)
            else:
                cap = f"artwork in style of {style_name}"
            captions.append(cap)

        tracker.status_message = "Loading base model & tokenizer..."
        print("[LoRA Training] Loading base SD components...")

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        weight_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        tokenizer = CLIPTokenizer.from_pretrained(model_id, subfolder="tokenizer")
        text_encoder = CLIPTextModel.from_pretrained(model_id, subfolder="text_encoder", torch_dtype=weight_dtype).to(device)
        vae = AutoencoderKL.from_pretrained(model_id, subfolder="vae", torch_dtype=weight_dtype).to(device)
        unet = UNet2DConditionModel.from_pretrained(model_id, subfolder="unet", torch_dtype=weight_dtype).to(device)
        noise_scheduler = DDPMScheduler.from_pretrained(model_id, subfolder="scheduler")

        vae.eval()
        text_encoder.eval()
        vae.requires_grad_(False)
        text_encoder.requires_grad_(False)
        unet.requires_grad_(False)

        # 3. Cache Latents and Text Embeddings (Massive speedup + low VRAM)
        tracker.status_message = "Caching image latents & embeddings..."
        cached_latents = []
        cached_embeds = []

        dataset = StyleDataset(image_paths, captions, size=512)
        dataloader = DataLoader(dataset, batch_size=1, shuffle=False)

        with torch.no_grad():
            for batch in dataloader:
                if tracker.should_stop:
                    tracker.status_message = "Stopped by user"
                    tracker.is_training = False
                    return

                pixel_values = batch["pixel_values"].to(device, dtype=weight_dtype)
                caption = batch["caption"][0]

                # Encode latent
                latents = vae.encode(pixel_values).latent_dist.sample()
                latents = latents * vae.config.scaling_factor
                cached_latents.append(latents.cpu())

                # Encode text
                inputs = tokenizer(
                    caption,
                    padding="max_length",
                    max_length=tokenizer.model_max_length,
                    truncation=True,
                    return_tensors="pt",
                ).to(device)
                prompt_embeds = text_encoder(inputs.input_ids)[0]
                cached_embeds.append(prompt_embeds.cpu())

        # Clean VAE and Text Encoder from GPU memory
        del vae
        del text_encoder
        del tokenizer
        torch.cuda.empty_cache()
        gc.collect()

        # 4. Attach LoRA to UNet
        tracker.status_message = "Configuring LoRA adapters on UNet..."
        lora_config = LoraConfig(
            r=lora_rank,
            lora_alpha=lora_rank * 2,
            target_modules=["to_k", "to_q", "to_v", "to_out.0"],
            init_lora_weights="gaussian",
        )
        unet.enable_gradient_checkpointing()
        unet_lora = get_peft_model(unet, lora_config)
        unet_lora.print_trainable_parameters()
        unet_lora.train()

        # Optimizer
        optimizer = torch.optim.AdamW(
            unet_lora.parameters(),
            lr=learning_rate,
            betas=(0.9, 0.999),
            weight_decay=1e-2,
            eps=1e-8,
        )

        num_images = len(cached_latents)
        tracker.status_message = f"Training LoRA ({total_steps} steps)..."
        step = 0

        # 5. Training loop
        while step < total_steps:
            if tracker.should_stop:
                tracker.status_message = "Training stopped by user"
                tracker.is_training = False
                return

            idx = step % num_images
            latents = cached_latents[idx].to(device, dtype=weight_dtype)
            encoder_hidden_states = cached_embeds[idx].to(device, dtype=weight_dtype)

            # Sample noise
            noise = torch.randn_like(latents)
            timesteps = torch.randint(
                0, noise_scheduler.config.num_train_timesteps, (1,), device=device
            ).long()

            # Add noise to latents (Forward diffusion)
            noisy_latents = noise_scheduler.add_noise(latents, noise, timesteps)

            # Predict the noise residual
            model_pred = unet_lora(noisy_latents, timesteps, encoder_hidden_states).sample

            # Compute loss
            target = noise
            loss = F.mse_loss(model_pred.float(), target.float(), reduction="mean")

            # Backprop
            loss.backward()
            torch.nn.utils.clip_grad_norm_(unet_lora.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()

            step += 1
            tracker.current_step = step
            tracker.current_loss = float(loss.item())
            tracker.progress_percent = (step / total_steps) * 100.0
            tracker.elapsed_seconds = time.time() - tracker.start_time

            if step > 5:
                avg_time_per_step = tracker.elapsed_seconds / step
                tracker.estimated_remaining_seconds = avg_time_per_step * (total_steps - step)

            if step % 25 == 0 or step == total_steps:
                print(f"[LoRA Step {step}/{total_steps}] Loss: {tracker.current_loss:.4f} ({tracker.progress_percent:.1f}%)")
                tracker.status_message = f"Step {step}/{total_steps} (Loss: {tracker.current_loss:.4f})"

        # 6. Save LoRA weights in PEFT format
        tracker.status_message = "Saving LoRA model..."
        # Extract and save adapter weights
        unet_lora.save_pretrained(os.path.join(output_dir, style_name))
        
        # If adapter_model.safetensors exists in subfolder, copy or link to output_dir/<style_name>.safetensors
        sub_safe = os.path.join(output_dir, style_name, "adapter_model.safetensors")
        if os.path.exists(sub_safe):
            import shutil
            shutil.copyfile(sub_safe, out_safetensors_path)

        tracker.saved_lora_path = out_safetensors_path
        tracker.status_message = f"Training completed successfully! Saved to {os.path.basename(out_safetensors_path)}"
        tracker.is_training = False
        print(f"[LoRA Training] Completed successfully: {out_safetensors_path}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        tracker.error_message = str(e)
        tracker.status_message = f"Error: {e}"
        tracker.is_training = False
    finally:
        # Cleanup
        torch.cuda.empty_cache()
        gc.collect()


def start_training_async(
    dataset_dir: str,
    style_name: str,
    total_steps: int = 400,
    vision_engine = None,
):
    """Launch training in a background daemon thread."""
    t = threading.Thread(
        target=run_lora_training,
        kwargs={
            "dataset_dir": dataset_dir,
            "style_name": style_name,
            "total_steps": total_steps,
            "vision_engine": vision_engine,
        },
        daemon=True,
    )
    t.start()
    return t
