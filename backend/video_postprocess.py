import os
import sys
import subprocess
import tempfile
from typing import List, Dict, Any, Optional

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = "ffmpeg"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BACKEND_DIR, "..", "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

def concatenate_video_clips(
    clip_filenames: List[str],
    output_filename: str
) -> Dict[str, Any]:
    """
    Concatenate multiple MP4 video clips into a single episode MP4 without re-encoding,
    using FFmpeg's concat demuxer (lossless and near-instant).
    Format naming convention: {Title}_{Episode:02d}_Full.mp4
    """
    if not clip_filenames:
        raise ValueError("No video clips provided for concatenation.")

    # Resolve full file paths
    resolved_paths = []
    for fn in clip_filenames:
        if os.path.isabs(fn) and os.path.exists(fn):
            resolved_paths.append(fn)
        else:
            p = os.path.join(OUTPUTS_DIR, os.path.basename(fn))
            if os.path.exists(p):
                resolved_paths.append(p)
            else:
                raise FileNotFoundError(f"Clip not found: {fn}")

    if not output_filename.endswith(".mp4"):
        output_filename += ".mp4"

    output_filepath = os.path.join(OUTPUTS_DIR, output_filename)

    # Create FFmpeg concat list file
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as list_f:
        concat_list_path = list_f.name
        for p in resolved_paths:
            # Escape single quotes and use forward slashes for Windows FFmpeg
            norm_path = p.replace("\\", "/").replace("'", "'\\''")
            list_f.write(f"file '{norm_path}'\n")

    try:
        # Fast concat demuxer (copy streams without quality degradation)
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            output_filepath
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[VideoPostprocess] FFmpeg concat failed: {res.stderr}", file=sys.stderr)
            raise RuntimeError(f"FFmpeg error: {res.stderr[:200]}")

        file_size = os.path.getsize(output_filepath)
        print(f"[VideoPostprocess] Successfully concatenated {len(resolved_paths)} clips into {output_filepath} ({file_size} bytes)")

        return {
            "status": "success",
            "filename": output_filename,
            "url": f"/outputs/{output_filename}",
            "clips_count": len(resolved_paths),
            "size_bytes": file_size,
            "clips": [os.path.basename(p) for p in resolved_paths]
        }
    finally:
        if os.path.exists(concat_list_path):
            try:
                os.remove(concat_list_path)
            except Exception:
                pass
