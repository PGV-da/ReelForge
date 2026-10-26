"""
ReelForge Configuration Module.

Loads and validates all environment variables at startup using pydantic-settings.
Fails fast with clear error messages if any required configuration is missing.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Automatically discover newly installed tools (e.g. FFmpeg via winget) on Windows
if sys.platform == "win32" and not shutil.which("ffmpeg"):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as _key:
            _reg_path, _ = winreg.QueryValueEx(_key, "Path")
            os.environ["PATH"] = f"{_reg_path};{os.environ.get('PATH', '')}"
    except Exception:
        pass


class Settings(BaseSettings):
    """Application-wide configuration loaded from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Telegram Bot ──────────────────────────────
    telegram_bot_token: str = Field(
        ...,
        description="Telegram Bot API token from @BotFather",
    )
    admin_user_ids: list[int] = Field(
        ...,
        description="Comma-separated list of authorized Telegram user IDs",
    )

    # ── Instagram / Meta Graph API (Optional) ────
    ig_user_id: Optional[str] = Field(
        default=None,
        description="Instagram Business/Creator Account numeric ID (optional)",
    )
    ig_access_token: Optional[str] = Field(
        default=None,
        description="Long-lived Meta Graph API access token (optional)",
    )
    graph_api_version: str = Field(
        default="v26.0",
        description="Meta Graph API version string",
    )

    # ── Branding ──────────────────────────────────
    watermark_text: str = Field(
        default="@your_handle",
        description="Username watermark to burn into processed videos",
    )

    # ── Whisper (Speech-to-Text) ──────────────────
    whisper_model_size: str = Field(
        default="base",
        description="faster-whisper model size: tiny, base, small, medium, large-v3",
    )

    # ── LLM Caption Generator ────────────────────
    llm_provider: Literal["groq", "gemini", "ollama"] = Field(
        default="groq",
        description="LLM API provider for caption generation",
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        description="API key for the chosen LLM provider (not needed for Ollama)",
    )
    llm_model_name: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model identifier for the LLM provider",
    )
    llm_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for Ollama or custom LLM endpoint",
    )

    # ── Paths ─────────────────────────────────────
    temp_base_dir: Path = Field(
        default=Path("/tmp/reelforge"),
        description="Base directory for temporary job working directories",
    )
    cookies_file: Optional[Path] = Field(
        default=None,
        description="Path to cookies.txt for yt-dlp (optional, for rate-limited accounts)",
    )
    font_path: Path = Field(
        default=Path("assets/fonts/Montserrat-Bold.ttf"),
        description="Path to the TTF font used for subtitles and watermark",
    )

    # ── Optional: Redis ───────────────────────────
    redis_url: Optional[str] = Field(
        default=None,
        description="Redis connection URL for FSM state persistence (e.g., redis://localhost:6379/0)",
    )

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> list[int]:
        """Parse user IDs (int, string, or list) into a list of integers."""
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        return v  # type: ignore[return-value]

    @property
    def graph_api_base(self) -> str:
        """Base URL for Meta Graph API requests."""
        return f"https://graph.facebook.com/{self.graph_api_version}"

    @property
    def ig_enabled(self) -> bool:
        """
        Check if Instagram publishing credentials are fully configured.
        Returns False if credentials are missing or set to placeholder strings.
        """
        if not self.ig_user_id or not self.ig_access_token:
            return False
        placeholders = {
            "your_instagram_business_account_id",
            "your_long_lived_access_token",
            "your_ig_user_id",
            "none",
            "",
        }
        if self.ig_user_id.strip().lower() in placeholders:
            return False
        if self.ig_access_token.strip().lower() in placeholders:
            return False
        return True


def load_settings() -> Settings:
    """Load and validate settings, exiting with a clear message on failure."""
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:
        print(f"❌ Configuration Error: {exc}", file=sys.stderr)
        print("   → Ensure your .env file exists and contains all required variables.", file=sys.stderr)
        print("   → See .env.example for a complete template.", file=sys.stderr)
        sys.exit(1)


# Singleton settings instance — imported throughout the application
settings = load_settings()
