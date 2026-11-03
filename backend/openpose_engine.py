import os
import io
import torch
from PIL import Image
from typing import Optional, Tuple
from controlnet_aux import OpenposeDetector

class PoseExtractor:
    """
    OpenPose / DWPose Skeleton Extractor for SDXL ControlNet.
    Runs fast on CPU / GPU to extract human wireframe poses (squatting, crouch, complex joints).
    """
    def __init__(self):
        self.detector = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def load_detector(self):
        if self.detector is None:
            print("[PoseExtractor] Initializing OpenposeDetector...")
            self.detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
            print("[PoseExtractor] OpenposeDetector ready!")

    def extract_pose(self, image: Image.Image, include_hand_and_face: bool = True) -> Image.Image:
        """Extract openpose wireframe skeleton from a PIL Image."""
        self.load_detector()
        
        # Ensure RGB
        if image.mode != "RGB":
            image = image.convert("RGB")

        pose_img = self.detector(
            image,
            detect_resolution=image.width,
            image_resolution=1024,
            include_body=True,
            include_hand=include_hand_and_face,
            include_face=include_hand_and_face
        )
        return pose_img

pose_extractor = PoseExtractor()
