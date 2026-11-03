import os
import math
from PIL import Image, ImageDraw

def create_studio_icon(output_path: str, size: int = 256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle background with deep purple-indigo gradient
    radius = 48
    # Draw base rounded rect
    draw.rounded_rectangle([8, 8, size - 8, size - 8], radius=radius, fill=(24, 24, 37, 255), outline=(99, 102, 241, 255), width=4)

    # Accent glow circle
    cx, cy = size // 2, size // 2
    draw.ellipse([cx - 70, cy - 70, cx + 70, cy + 70], fill=(79, 70, 229, 120))

    # Draw sparkle / diamond star
    points = [
        (cx, cy - 64),
        (cx + 18, cy - 18),
        (cx + 64, cy),
        (cx + 18, cy + 18),
        (cx, cy + 64),
        (cx - 18, cy + 18),
        (cx - 64, cy),
        (cx - 18, cy - 18)
    ]
    draw.polygon(points, fill=(236, 72, 153, 255))

    # Inner bright star
    inner_points = [
        (cx, cy - 40),
        (cx + 10, cy - 10),
        (cx + 40, cy),
        (cx + 10, cy + 10),
        (cx, cy + 40),
        (cx - 10, cy + 10),
        (cx - 40, cy),
        (cx - 10, cy - 10)
    ]
    draw.polygon(inner_points, fill=(255, 255, 255, 255))

    # Small satellite sparkles
    draw.ellipse([cx + 45, cy - 50, cx + 55, cy - 40], fill=(56, 189, 248, 255))
    draw.ellipse([cx - 52, cy + 42, cx - 44, cy + 50], fill=(168, 85, 247, 255))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")
    print(f"Generated icon at {output_path}")

if __name__ == "__main__":
    out_file = os.path.join(os.path.dirname(__file__), "icon.png")
    create_studio_icon(out_file)
