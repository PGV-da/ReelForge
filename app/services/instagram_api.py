"""
ReelForge Instagram Graph API Publisher.

Implements the Meta Instagram Graph API v26.0 Resumable Direct Binary Upload
protocol for publishing Reels without requiring external cloud storage.

Flow:
  1. Initialize an upload session (POST /media → container_id + upload_uri)
  2. Upload binary .mp4 directly to rupload.facebook.com
  3. Poll container status until FINISHED
  4. Publish the container (POST /media_publish → media_id)
  5. Retrieve the live permalink
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import get_job_logger


class InstagramAPIError(Exception):
    """Raised when any Instagram Graph API operation fails."""

    def __init__(self, message: str, status_code: Optional[int] = None, error_data: Optional[dict] = None):
        self.status_code = status_code
        self.error_data = error_data or {}
        super().__init__(message)


class ContainerStatusError(InstagramAPIError):
    """Raised when a container enters an ERROR or EXPIRED state."""


class UploadTimeoutError(InstagramAPIError):
    """Raised when container processing exceeds the timeout."""


class InstagramPublisher:
    """
    Client for publishing Reels to Instagram via the Meta Graph API.

    Uses the Resumable Upload Protocol so the video binary is uploaded
    directly from the local filesystem — no S3 or cloud storage needed.

    Attributes:
        ig_user_id: Instagram Business Account numeric ID.
        access_token: Long-lived Meta Graph API access token.
        api_base: Base URL for Graph API requests.
    """

    def __init__(
        self,
        ig_user_id: Optional[str] = None,
        access_token: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self.ig_user_id = ig_user_id or settings.ig_user_id
        self.access_token = access_token or settings.ig_access_token
        api_ver = api_version or settings.graph_api_version
        self.api_base = f"https://graph.facebook.com/{api_ver}"

    # ── Step 1: Initialize Upload Session ─────────

    async def init_upload_session(
        self,
        caption: str,
        thumb_offset_ms: int = 0,
        job_id: str = "unknown",
    ) -> tuple[str, str]:
        """
        Create a Resumable Upload media container on Meta's servers.

        Args:
            caption: Instagram caption text for the Reel.
            thumb_offset_ms: Cover photo timestamp offset in milliseconds.
            job_id: Job identifier for logging.

        Returns:
            Tuple of (container_id, upload_uri).

        Raises:
            InstagramAPIError: If the API request fails.
        """
        log = get_job_logger(job_id)

        if not self.ig_user_id or not self.access_token:
            raise InstagramAPIError("Instagram upload is disabled or credentials (IG_USER_ID, IG_ACCESS_TOKEN) are missing.")

        url = f"{self.api_base}/{self.ig_user_id}/media"

        payload = {
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption,
            "thumb_offset": thumb_offset_ms,
            "share_to_feed": True,
            "access_token": self.access_token,
        }

        log.info("Initializing upload session")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data=payload)

        data = response.json()

        if response.status_code != 200 or "error" in data:
            error_info = data.get("error", {})
            raise InstagramAPIError(
                f"Failed to init upload session: {error_info.get('message', response.text[:300])}",
                status_code=response.status_code,
                error_data=error_info,
            )

        container_id = data.get("id")
        upload_uri = data.get("uri")

        if not container_id or not upload_uri:
            raise InstagramAPIError(
                f"Missing container_id or upload_uri in response: {data}",
                status_code=response.status_code,
            )

        log.info("Upload session initialized", container_id=container_id)
        return container_id, upload_uri

    # ── Step 2: Upload Binary Video ───────────────

    async def upload_binary(
        self,
        upload_uri: str,
        file_path: Path,
        job_id: str = "unknown",
    ) -> None:
        """
        Upload the local video binary to Meta's resumable upload endpoint.

        Reads the file and sends it as raw bytes with appropriate headers.

        Args:
            upload_uri: The ``rupload.facebook.com`` URI returned by init_upload_session.
            file_path: Path to the local .mp4 file to upload.
            job_id: Job identifier for logging.

        Raises:
            InstagramAPIError: If the upload request fails.
            FileNotFoundError: If the video file doesn't exist.
        """
        log = get_job_logger(job_id)

        if not file_path.exists():
            raise FileNotFoundError(f"Video file not found: {file_path}")

        file_size = file_path.stat().st_size
        log.info("Uploading video binary", size_mb=f"{file_size / 1_048_576:.1f}", uri=upload_uri[:80])

        # Read file content
        with open(file_path, "rb") as f:
            file_data = f.read()

        headers = {
            "Authorization": f"OAuth {self.access_token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": "application/octet-stream",
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                upload_uri,
                headers=headers,
                content=file_data,
            )

        if response.status_code not in (200, 201):
            raise InstagramAPIError(
                f"Binary upload failed: {response.text[:300]}",
                status_code=response.status_code,
            )

        log.info("Video binary uploaded successfully")

    # ── Step 3: Poll Container Status ─────────────

    async def wait_until_finished(
        self,
        container_id: str,
        timeout_sec: int = 300,
        poll_interval: int = 10,
        job_id: str = "unknown",
    ) -> None:
        """
        Poll the container status until processing is complete.

        Uses exponential backoff starting from ``poll_interval`` seconds.

        Args:
            container_id: Media container ID to poll.
            timeout_sec: Maximum seconds to wait before timing out.
            poll_interval: Initial polling interval in seconds.
            job_id: Job identifier for logging.

        Raises:
            ContainerStatusError: If the container enters ERROR or EXPIRED state.
            UploadTimeoutError: If processing exceeds the timeout.
        """
        log = get_job_logger(job_id)
        url = f"{self.api_base}/{container_id}"
        params = {
            "fields": "status_code,status",
            "access_token": self.access_token,
        }

        elapsed = 0
        current_interval = poll_interval

        log.info("Polling container status", container_id=container_id, timeout=timeout_sec)

        while elapsed < timeout_sec:
            await asyncio.sleep(current_interval)
            elapsed += current_interval

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)

            data = response.json()

            if response.status_code != 200:
                log.warning("Status poll request failed", status=response.status_code)
                continue

            status_code = data.get("status_code", "UNKNOWN")
            status_detail = data.get("status", "")

            log.debug("Container status", status_code=status_code, detail=status_detail, elapsed=f"{elapsed}s")

            if status_code == "FINISHED":
                log.info("Container processing complete", elapsed=f"{elapsed}s")
                return

            if status_code in ("ERROR", "EXPIRED"):
                raise ContainerStatusError(
                    f"Container {container_id} entered {status_code} state: {status_detail}",
                    error_data=data,
                )

            # Exponential backoff (cap at 30s)
            current_interval = min(current_interval * 1.5, 30)

        raise UploadTimeoutError(
            f"Container {container_id} did not finish within {timeout_sec}s"
        )

    # ── Step 4: Publish Container ─────────────────

    async def publish_container(
        self,
        container_id: str,
        job_id: str = "unknown",
    ) -> str:
        """
        Publish a finished media container to Instagram.

        Args:
            container_id: The processed media container ID.
            job_id: Job identifier for logging.

        Returns:
            The live Instagram permalink URL.

        Raises:
            InstagramAPIError: If publishing or permalink retrieval fails.
        """
        log = get_job_logger(job_id)
        publish_url = f"{self.api_base}/{self.ig_user_id}/media_publish"

        payload = {
            "creation_id": container_id,
            "access_token": self.access_token,
        }

        log.info("Publishing container", container_id=container_id)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(publish_url, data=payload)

        data = response.json()

        if response.status_code != 200 or "error" in data:
            error_info = data.get("error", {})
            raise InstagramAPIError(
                f"Publish failed: {error_info.get('message', response.text[:300])}",
                status_code=response.status_code,
                error_data=error_info,
            )

        media_id = data.get("id")
        if not media_id:
            raise InstagramAPIError("No media_id returned in publish response")

        log.info("Published successfully", media_id=media_id)

        # Fetch permalink
        permalink = await self._get_permalink(media_id, job_id)
        return permalink

    # ── Helper: Get Permalink ─────────────────────

    async def _get_permalink(self, media_id: str, job_id: str) -> str:
        """Fetch the live Instagram permalink for a published media item."""
        log = get_job_logger(job_id)
        url = f"{self.api_base}/{media_id}"
        params = {
            "fields": "permalink",
            "access_token": self.access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)

        data = response.json()

        if response.status_code != 200:
            log.warning("Failed to fetch permalink", status=response.status_code)
            return f"https://www.instagram.com/reel/ (permalink unavailable)"

        permalink = data.get("permalink", "")
        log.info("Permalink retrieved", permalink=permalink)
        return permalink

    # ── Utility: Check Token Health ───────────────

    async def check_token_health(self) -> dict:
        """
        Check the current access token's validity and remaining lifetime.

        Returns:
            Dict with 'is_valid', 'expires_at', 'scopes', and 'app_id' fields.
        """
        if not self.access_token:
            return {
                "is_valid": False,
                "expires_at": 0,
                "scopes": [],
                "app_id": "",
                "error": {"message": "No access token configured in .env"},
            }

        url = "https://graph.facebook.com/debug_token"
        params = {
            "input_token": self.access_token,
            "access_token": self.access_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)

        data = response.json()
        token_data = data.get("data", {})

        return {
            "is_valid": token_data.get("is_valid", False),
            "expires_at": token_data.get("expires_at", 0),
            "scopes": token_data.get("scopes", []),
            "app_id": token_data.get("app_id", ""),
            "error": token_data.get("error", {}),
        }

    # ── Full Publish Pipeline ─────────────────────

    async def publish_reel(
        self,
        video_path: Path,
        caption: str,
        thumb_offset_ms: int = 0,
        job_id: str = "unknown",
    ) -> tuple[str, str]:
        """
        Execute the full publishing pipeline: init → upload → poll → publish.

        Args:
            video_path: Path to the processed .mp4 video file.
            caption: Instagram caption text.
            thumb_offset_ms: Cover thumbnail offset in milliseconds.
            job_id: Job identifier for logging.

        Returns:
            Tuple of (media_id, permalink_url).

        Raises:
            InstagramAPIError: If any step in the pipeline fails.
        """
        log = get_job_logger(job_id)
        log.info("Starting full publish pipeline")

        # Step 1: Initialize
        container_id, upload_uri = await self.init_upload_session(
            caption=caption,
            thumb_offset_ms=thumb_offset_ms,
            job_id=job_id,
        )

        # Step 2: Upload binary
        await self.upload_binary(upload_uri, video_path, job_id)

        # Step 3: Wait for processing
        await self.wait_until_finished(container_id, job_id=job_id)

        # Step 4: Publish
        permalink = await self.publish_container(container_id, job_id)

        log.info("Reel published to Instagram!", permalink=permalink)
        return container_id, permalink
