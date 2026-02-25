"""Claude Vision API wrapper. Adapted from art-journal VisionService."""

import anthropic
import asyncio
import base64
from typing import Optional
from app.config import get_settings


class VisionService:
    """Wrapper for Claude API — image analysis and text synthesis.

    Uses anthropic.AsyncAnthropic so all calls are truly async-compatible
    and don't block the FastAPI event loop during background tasks.
    """

    def __init__(self):
        settings = get_settings()
        # AsyncAnthropic is the async-native client — safe to await in FastAPI background tasks
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.model_name   # single source of truth from config

    async def analyze_batch(
        self,
        images: list[tuple[bytes, str, str]],  # (image_bytes, media_type, identifier_label)
        prompt: str,
        max_tokens: int = 4000
    ) -> str:
        """
        Send multiple images + one prompt in a single API call.
        Claude sees all images before the prompt text.

        Args:
            images: list of (raw_bytes, media_type, label)
            prompt: The analysis prompt sent after all images
            max_tokens: Max response tokens

        Returns:
            Claude's full text response
        """
        content = []
        for image_data, media_type, identifier in images:
            content.append({
                "type": "text",
                "text": f"[Drawing: {identifier}]"
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_data).decode("utf-8")
                }
            })
        content.append({"type": "text", "text": prompt})

        message = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}]
        )
        return message.content[0].text

    async def synthesize_text(
        self,
        text: str,
        max_tokens: int = 2000
    ) -> str:
        """
        Send a pure text prompt to Claude (no images).
        Used for lens discovery and lens annotation batches.

        Args:
            text: The full prompt text
            max_tokens: Max response tokens

        Returns:
            Claude's text response
        """
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": text}]
        )
        return message.content[0].text


# ─── Singleton ────────────────────────────────────────────────────────────────

_vision_service: Optional[VisionService] = None


def get_vision_service() -> VisionService:
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service
