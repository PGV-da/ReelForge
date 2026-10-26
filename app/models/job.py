"""
ReelForge-Bot Job Models.

Pydantic models representing a Reel processing job, its metadata,
lifecycle status, and generated outputs. These models are the single
source of truth for all job state exchanged between services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    """Lifecycle states for a ReelForge processing job."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    PROCESSING_VIDEO = "processing_video"
    GENERATING_CAPTION = "generating_caption"
    AWAITING_APPROVAL = "awaiting_approval"
    EDITING_CAPTION = "editing_caption"
    EDITING_THUMBNAIL = "editing_thumbnail"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    APPROVED = "approved"
    DISCARDED = "discarded"
    FAILED = "failed"


class VideoMetadata(BaseModel):
    """Metadata extracted from the source Instagram Reel by yt-dlp."""

    uploader_id: str = Field(default="unknown", description="Original creator's Instagram handle")
    description: str = Field(default="", description="Original post caption")
    duration: float = Field(default=0.0, description="Video duration in seconds")
    webpage_url: str = Field(default="", description="Original Instagram URL")
    width: int = Field(default=0, description="Original video width in pixels")
    height: int = Field(default=0, description="Original video height in pixels")


class GeneratedCaption(BaseModel):
    """Structured caption output from the LLM service."""

    hook_line: str = Field(default="", description="Scroll-stopping first line (<120 chars)")
    value_body: str = Field(default="", description="2-3 concise sentences summarizing the Reel")
    cta_attribution: str = Field(default="", description="Call-to-action with credit to original creator")
    hashtags: str = Field(default="", description="5-8 niche-relevant hashtags")

    @property
    def full_caption(self) -> str:
        """Assemble the complete Instagram caption string."""
        parts = [
            self.hook_line,
            "",
            self.value_body,
            "",
            self.cta_attribution,
            "",
            self.hashtags,
        ]
        return "\n".join(parts).strip()


class ReelJob(BaseModel):
    """
    Central model representing a single Reel processing job.

    Tracks the full lifecycle from URL ingestion through publishing,
    storing file paths, metadata, generated content, and status.
    """

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    chat_id: int = Field(..., description="Telegram chat ID of the requesting admin")
    source_url: str = Field(..., description="Original Instagram Reel/Post URL")
    status: JobStatus = Field(default=JobStatus.PENDING)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Paths (populated during pipeline stages) ──
    work_dir: Optional[Path] = Field(default=None, description="Isolated temporary directory for this job")
    raw_video_path: Optional[Path] = Field(default=None, description="Downloaded source video path")
    srt_path: Optional[Path] = Field(default=None, description="Generated subtitle file path")
    processed_video_path: Optional[Path] = Field(default=None, description="Final processed video path")
    thumbnail_path: Optional[Path] = Field(default=None, description="Extracted/generated thumbnail path")

    # ── Extracted Data ────────────────────────────
    metadata: VideoMetadata = Field(default_factory=VideoMetadata)
    transcript: str = Field(default="", description="Full plain-text transcript from faster-whisper")

    # ── Generated Content ─────────────────────────
    caption: GeneratedCaption = Field(default_factory=GeneratedCaption)
    custom_caption: Optional[str] = Field(
        default=None,
        description="User-edited caption override (takes priority over generated caption)",
    )
    thumb_offset_ms: int = Field(
        default=0,
        description="Thumbnail timestamp offset in milliseconds for IG API",
    )

    # ── Publishing Outputs ────────────────────────
    ig_container_id: Optional[str] = Field(default=None, description="Meta API container ID")
    ig_media_id: Optional[str] = Field(default=None, description="Published Instagram media ID")
    ig_permalink: Optional[str] = Field(default=None, description="Live Instagram permalink URL")

    # ── Telegram Message References ───────────────
    status_message_id: Optional[int] = Field(
        default=None,
        description="Telegram message ID of the current status/preview message (for editing)",
    )

    @property
    def effective_caption(self) -> str:
        """Return the user-edited caption if set, otherwise the AI-generated one."""
        return self.custom_caption if self.custom_caption else self.caption.full_caption

    class Config:
        arbitrary_types_allowed = True
