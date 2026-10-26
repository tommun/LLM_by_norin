import os
import io
import csv
from typing import List, Tuple, Dict, Any, Union
import numpy as np
from PIL import Image
import onnxruntime as ort
import huggingface_hub

TAGGER_REPO_ID = "SmilingWolf/wd-v1-4-convnext-tagger-v2"

class DanbooruTaggerEngine:
    """
    WD14 / SmilingWolf ConvNeXt Tagger Engine for Danbooru/Gelbooru tags extraction.
    Runs via ONNX on CPU with 0 MB GPU VRAM consumption and <0.2s latency.
    """
    def __init__(self, repo_id: str = TAGGER_REPO_ID):
        self.repo_id = repo_id
        self.session: ort.InferenceSession = None
        self.tag_names: List[str] = []
        self.rating_indices: List[int] = []
        self.general_indices: List[int] = []
        self.character_indices: List[int] = []
        self.input_name: str = ""
        self.is_ready: bool = False

    def load_model(self):
        if self.is_ready and self.session is not None:
            return

        print(f"[TaggerEngine] Loading WD14 Danbooru Tagger from {self.repo_id}...")
        model_path = huggingface_hub.hf_hub_download(self.repo_id, "model.onnx")
        tags_path = huggingface_hub.hf_hub_download(self.repo_id, "selected_tags.csv")

        with open(tags_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [r for r in reader]

        self.tag_names = [r[1] for r in rows]
        self.general_indices = [i for i, r in enumerate(rows) if r[2] == "0"]
        self.character_indices = [i for i, r in enumerate(rows) if r[2] == "4"]
        self.rating_indices = [i for i, r in enumerate(rows) if r[2] == "9"]

        # Run on CPU to save 100% GPU VRAM for LLM & SDXL
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.is_ready = True
        print(f"[TaggerEngine] Loaded {len(self.tag_names)} Danbooru tags successfully!")

    def extract_tags(
        self,
        image_input: Union[Image.Image, bytes, str],
        general_threshold: float = 0.25,
        character_threshold: float = 0.5
    ) -> Dict[str, Any]:
        """
        Extracts Danbooru/Gelbooru tags from image.
        Returns: {
            "tags": ["tag1", "tag2", ...],
            "tag_scores": [("tag1", score), ...],
            "character_tags": [...],
            "rating": "general" | "sensitive" | "questionable" | "explicit"
        }
        """
        if not self.is_ready:
            self.load_model()

        # Resolve Image
        if isinstance(image_input, Image.Image):
            img = image_input
        elif isinstance(image_input, bytes):
            img = Image.open(io.BytesIO(image_input))
        elif isinstance(image_input, str):
            if image_input.startswith("data:image"):
                import base64
                header, b64_str = image_input.split(",", 1)
                img = Image.open(io.BytesIO(base64.b64decode(b64_str)))
            elif os.path.exists(image_input):
                img = Image.open(image_input)
            else:
                raise ValueError(f"Invalid image input string: {image_input[:50]}")
        else:
            raise TypeError(f"Unsupported image type: {type(image_input)}")

        if img.mode != "RGB":
            img = img.convert("RGB")

        # Standard WD14 pre-processing: Pad with white to square and resize to 448x448
        target_size = 448
        w, h = img.size
        max_dim = max(w, h)
        padded_img = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
        padded_img.paste(img, ((max_dim - w) // 2, (max_dim - h) // 2))
        resized_img = padded_img.resize((target_size, target_size), Image.Resampling.BICUBIC)

        # Convert to BGR array
        img_array = np.array(resized_img, dtype=np.float32)[:, :, ::-1]
        img_tensor = np.expand_dims(img_array, axis=0)

        # Inference
        preds = self.session.run(None, {self.input_name: img_tensor})[0][0]

        # Extract general tags (poses, anatomy, lighting, clothing, attributes)
        detected_tags: List[Tuple[str, float]] = []
        for idx in self.general_indices:
            score = float(preds[idx])
            if score >= general_threshold:
                detected_tags.append((self.tag_names[idx], score))

        # Sort tags by confidence descending
        detected_tags.sort(key=lambda x: x[1], reverse=True)

        # Extract character tags
        char_tags: List[Tuple[str, float]] = []
        for idx in self.character_indices:
            score = float(preds[idx])
            if score >= character_threshold:
                char_tags.append((self.tag_names[idx], score))

        # Extract rating
        ratings = ["general", "sensitive", "questionable", "explicit"]
        rating_scores = {ratings[i]: float(preds[self.rating_indices[i]]) for i in range(len(ratings))}
        detected_rating = max(rating_scores.items(), key=lambda x: x[1])[0]

        tag_list = [t[0].replace("_", " ") for t in detected_tags]
        raw_tag_list = [t[0] for t in detected_tags]

        return {
            "tags": tag_list,
            "raw_tags": raw_tag_list,
            "tag_scores": detected_tags,
            "character_tags": [t[0] for t in char_tags],
            "rating": detected_rating,
            "tag_string": ", ".join(tag_list)
        }

tagger = DanbooruTaggerEngine()
