"""
CLIP Client Service - calls the GPU Chinese-CLIP microservice.

Mirrors the API-mode pattern of sam2_service: the main backend stays
lightweight (no torch) while image/text embedding runs in anno-clip.
"""
import logging

import httpx

from app.core.config import settings
from app.schemas.clip import EmbedResponse, TextEmbedRequest

logger = logging.getLogger(__name__)


class ClipClientService:
    def __init__(self, api_url: str | None = None) -> None:
        self._api_url = (api_url or settings.CLIP_API_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._api_url,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get("/health")
            response.raise_for_status()
            return response.json().get("status") == "healthy"
        except Exception as exc:
            logger.warning("CLIP service health check failed: %s", exc)
            return False

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = await self._get_client()
        payload = TextEmbedRequest(texts=texts)
        response = await client.post("/embed/text", json=payload.model_dump())
        response.raise_for_status()
        return EmbedResponse.model_validate(response.json()).vectors

    async def embed_images(self, image_bytes_list: list[bytes]) -> list[list[float]]:
        if not image_bytes_list:
            return []
        client = await self._get_client()
        files = [
            ("images", (f"image_{index}.jpg", data, "image/jpeg"))
            for index, data in enumerate(image_bytes_list)
        ]
        response = await client.post("/embed/images", files=files)
        response.raise_for_status()
        return EmbedResponse.model_validate(response.json()).vectors


clip_client = ClipClientService()
