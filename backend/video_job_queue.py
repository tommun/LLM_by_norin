import os
import sys
import time
import uuid
import asyncio
import threading
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field

@dataclass
class VideoJob:
    job_id: str
    user_instruction: str
    status: str = "pending"  # pending, generating_prompts, generating_keyframe, generating_video, completed, failed
    progress: int = 0         # 0 - 100
    status_text: str = "ジョブ待機中..."
    reference_image: Optional[str] = None
    character_id: Optional[str] = None
    style_id: Optional[str] = None
    keyframe_prompt: Optional[str] = None
    motion_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    keyframe_url: Optional[str] = None
    video_url: Optional[str] = None
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

class VideoJobQueue:
    """
    In-memory asynchronous job queue for long-running video generation tasks.
    Enables real-time progress polling from Discord Bot and WebUI.
    """
    def __init__(self):
        self.jobs: Dict[str, VideoJob] = {}
        self.lock = threading.Lock()
        self._listeners: Dict[str, list] = {}

    def create_job(
        self,
        user_instruction: str,
        reference_image: Optional[str] = None,
        character_id: Optional[str] = None,
        style_id: Optional[str] = None
    ) -> VideoJob:
        with self.lock:
            job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            job = VideoJob(
                job_id=job_id,
                user_instruction=user_instruction,
                reference_image=reference_image,
                character_id=character_id,
                style_id=style_id
            )
            self.jobs[job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[VideoJob]:
        with self.lock:
            return self.jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        status_text: Optional[str] = None,
        keyframe_prompt: Optional[str] = None,
        motion_prompt: Optional[str] = None,
        keyframe_url: Optional[str] = None,
        video_url: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if status_text is not None:
                job.status_text = status_text
            if keyframe_prompt is not None:
                job.keyframe_prompt = keyframe_prompt
            if motion_prompt is not None:
                job.motion_prompt = motion_prompt
            if keyframe_url is not None:
                job.keyframe_url = keyframe_url
            if video_url is not None:
                job.video_url = video_url
            if result_data is not None:
                job.result_data = result_data
            if error_message is not None:
                job.error_message = error_message
            job.updated_at = time.time()

# Global singleton
job_queue = VideoJobQueue()
