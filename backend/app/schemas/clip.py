"""Chinese-CLIP embedding microservice wire schemas.

Shared by the standalone CLIP GPU microservice (``microservices/clip``) and
the backend's ``ClipClientService`` so request/response models live in one
place.
"""
from typing import List

from pydantic import BaseModel


class TextEmbedRequest(BaseModel):
    """Batch text embedding request."""

    texts: List[str]


class EmbedResponse(BaseModel):
    """Normalised embedding vectors returned by the CLIP microservice."""

    model: str
    dimensions: int
    vectors: List[List[float]]
