"""
CLIP Client Service - calls the GPU Chinese-CLIP microservice.

Mirrors the API-mode pattern of sam2_service: the main backend stays
lightweight (no torch) while image/text embedding runs in anno-clip.
"""
import logging
from typing import List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class ClipClientService:
    def __init__(self, api_url: Optional[str] = None) -> None:
        self._api_url = (api_url or settings.CLIP_API_URL).rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

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

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        client = await self._get_client()
        response = await client.post("/embed/text", json={"texts": texts})
        response.raise_for_status()
        return response.json()["vectors"]

    async def embed_images(self, image_bytes_list: List[bytes]) -> List[List[float]]:
        if not image_bytes_list:
            return []
        client = await self._get_client()
        files = [
            ("images", (f"image_{index}.jpg", data, "image/jpeg"))
            for index, data in enumerate(image_bytes_list)
        ]
        response = await client.post("/embed/images", files=files)
        response.raise_for_status()
        return response.json()["vectors"]


clip_client = ClipClientService()
