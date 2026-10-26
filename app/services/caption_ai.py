"""
ReelForge AI Caption & Hashtag Generator.

Pluggable LLM client supporting Groq, Google Gemini, and local Ollama
for generating high-converting Instagram captions with hooks, value body,
CTAs, attribution, and niche-relevant hashtags.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Optional

import httpx

from app.config import settings
from app.models.job import GeneratedCaption
from app.utils.logger import get_job_logger


class CaptionGenerationError(Exception):
    """Raised when the LLM fails to generate or parse a caption."""


# ── Prompt Template ───────────────────────────────

CAPTION_PROMPT_TEMPLATE = """\
You are an expert Instagram growth strategist and viral content copywriter.

Your task is to write a high-converting Instagram Reel caption based on the following inputs:

**Spoken Transcript from the Reel:**
{transcript}

**Original Post Caption:**
{original_caption}

**Original Creator Handle:** @{original_creator}
**Brand Handle:** @{brand_handle}

---

**OUTPUT FORMAT — Return ONLY a valid JSON object with these exact keys:**

{{
  "hook_line": "A scroll-stopping, curiosity-driven first line. Max 120 characters. Use emojis strategically. This line MUST make people stop scrolling.",
  "value_body": "2-3 concise, punchy sentences that summarize the core value or insight from this Reel. Write in a conversational, relatable tone. Add line breaks between sentences for readability.",
  "cta_attribution": "Follow @{brand_handle} for more! 🔥\\n(📹 Credit: @{original_creator})",
  "hashtags": "#hashtag1 #hashtag2 #hashtag3 #hashtag4 #hashtag5 #hashtag6"
}}

**RULES:**
1. The hook_line MUST be under 120 characters and extremely attention-grabbing.
2. The value_body should be 2-3 sentences, NOT a wall of text.
3. Include exactly 5-8 hashtags that are niche-relevant (not generic like #viral or #fyp).
4. Keep the total caption concise — Instagram truncates long captions.
5. Return ONLY the JSON object, no markdown code fences, no extra text.
"""


# ── LLM API Endpoints ────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


async def generate_caption(
    transcript: str,
    original_caption: str,
    original_creator: str,
    brand_handle: Optional[str] = None,
    job_id: str = "unknown",
) -> GeneratedCaption:
    """
    Generate an Instagram caption using the configured LLM provider.

    Args:
        transcript: Plain-text transcript from the Reel's audio.
        original_caption: Original post caption from the source Reel.
        original_creator: Instagram handle of the original creator.
        brand_handle: Your Instagram handle (defaults to watermark text from config).
        job_id: Job identifier for logging.

    Returns:
        Structured GeneratedCaption with hook, body, CTA, and hashtags.

    Raises:
        CaptionGenerationError: If the LLM call fails or response cannot be parsed.
    """
    log = get_job_logger(job_id)
    effective_brand = brand_handle or settings.watermark_text.lstrip("@")

    # Handle empty transcript gracefully
    effective_transcript = transcript.strip() if transcript else "(No speech detected — music-only Reel)"
    effective_caption = original_caption.strip() if original_caption else "(No original caption available)"

    prompt = CAPTION_PROMPT_TEMPLATE.format(
        transcript=effective_transcript,
        original_caption=effective_caption,
        original_creator=original_creator,
        brand_handle=effective_brand,
    )

    log.info("Generating caption via LLM", provider=settings.llm_provider, model=settings.llm_model_name)

    # Route to the appropriate provider
    provider_map = {
        "groq": _call_groq,
        "gemini": _call_gemini,
        "ollama": _call_ollama,
    }

    handler = provider_map.get(settings.llm_provider)
    if handler is None:
        raise CaptionGenerationError(f"Unknown LLM provider: {settings.llm_provider}")

    raw_response = await handler(prompt, job_id)
    caption = _parse_llm_response(raw_response, job_id)

    log.info(
        "Caption generated",
        hook_length=len(caption.hook_line),
        hashtag_count=len(caption.hashtags.split("#")) - 1,
    )

    return caption


def _resolve_model_name(provider: str) -> str:
    """Resolve a suitable model name based on the configured provider."""
    model = settings.llm_model_name.strip()
    if provider == "gemini":
        if "llama" in model.lower() or "groq" in model.lower() or not model or "2.0-flash" in model.lower() or "latest" in model.lower():
            return "gemini-3.5-flash"
    elif provider == "groq":
        if "gemini" in model.lower() or not model:
            return "llama-3.3-70b-versatile"
    return model


async def _call_groq(prompt: str, job_id: str) -> str:
    """Call the Groq API (OpenAI-compatible endpoint)."""
    log = get_job_logger(job_id)

    if not settings.llm_api_key:
        raise CaptionGenerationError("LLM_API_KEY is required for Groq provider")

    model_name = _resolve_model_name("groq")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "You are an expert Instagram content strategist. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
            },
        )

    if response.status_code != 200:
        log.error("Groq API error", status=response.status_code, body=response.text[:500])
        raise CaptionGenerationError(f"Groq API returned {response.status_code}: {response.text[:300]}")

    data = response.json()
    return data["choices"][0]["message"]["content"]


async def _call_gemini(prompt: str, job_id: str) -> str:
    """Call the Google Gemini API with automatic model fallback."""
    log = get_job_logger(job_id)

    if not settings.llm_api_key:
        raise CaptionGenerationError("LLM_API_KEY is required for Gemini provider")

    primary_model = _resolve_model_name("gemini")
    model_candidates = [primary_model]
    for fallback in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"):
        if fallback not in model_candidates:
            model_candidates.append(fallback)

    last_error = ""
    for model_name in model_candidates:
        url = GEMINI_API_URL.format(model=model_name)

        for attempt in range(2):
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    params={"key": settings.llm_api_key},
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [
                            {
                                "parts": [{"text": prompt}],
                            }
                        ],
                        "generationConfig": {
                            "temperature": 0.7,
                            "maxOutputTokens": 2048,
                            "responseMimeType": "application/json",
                        },
                    },
                )

            if response.status_code == 200:
                data = response.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as exc:
                    raise CaptionGenerationError(f"Unexpected Gemini response structure: {exc}") from exc

            if response.status_code in (503, 429) and attempt == 0:
                await asyncio.sleep(2.0)
                continue

            last_error = response.text[:300]
            log.warning(f"Gemini API model {model_name} returned {response.status_code}, trying fallback...")
            break

    log.error("Gemini API error across all models", error=last_error)
    raise CaptionGenerationError(f"Gemini API returned error: {last_error}")


async def _call_ollama(prompt: str, job_id: str) -> str:
    """Call a local Ollama API instance."""
    log = get_job_logger(job_id)

    url = f"{settings.llm_base_url.rstrip('/')}/api/generate"

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            json={
                "model": settings.llm_model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.7,
                    "num_predict": 1024,
                },
            },
        )

    if response.status_code != 200:
        log.error("Ollama API error", status=response.status_code, body=response.text[:500])
        raise CaptionGenerationError(f"Ollama API returned {response.status_code}: {response.text[:300]}")

    data = response.json()
    return data.get("response", "")


def _parse_llm_response(raw: str, job_id: str) -> GeneratedCaption:
    """
    Parse the raw LLM response string into a structured GeneratedCaption.

    Handles various response formats including markdown-wrapped JSON,
    extra whitespace, and partial responses.

    Args:
        raw: Raw text response from the LLM.
        job_id: Job identifier for logging.

    Returns:
        Parsed GeneratedCaption model.

    Raises:
        CaptionGenerationError: If the response cannot be parsed into valid JSON.
    """
    log = get_job_logger(job_id)

    # Strip markdown code fences if present
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned, strict=False)
    except json.JSONDecodeError as exc:
        log.warning("Failed to parse LLM JSON response", error=str(exc), raw_preview=raw[:300])

        # Attempt to extract JSON from the response
        json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(), strict=False)
            except json.JSONDecodeError:
                raise CaptionGenerationError(
                    f"Could not parse LLM response as JSON: {exc}"
                ) from exc
        else:
            raise CaptionGenerationError(
                f"No JSON object found in LLM response: {raw[:300]}"
            ) from exc

    return GeneratedCaption(
        hook_line=data.get("hook_line", "").strip(),
        value_body=data.get("value_body", "").strip(),
        cta_attribution=data.get("cta_attribution", "").strip(),
        hashtags=data.get("hashtags", "").strip(),
    )
