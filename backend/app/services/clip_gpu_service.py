"""
CLIP GPU Microservice - Chinese-CLIP image/text embeddings.

Runs as a separate GPU container (same pattern as sam2_gpu_service).
The main backend calls this for semantic scene search.

Endpoints:
  GET  /health
  POST /embed/text    {"texts": ["汽车场景", ...]}            -> normalized vectors
  POST /embed/images  multipart files (name="images")         -> normalized vectors
"""
import io
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List

import numpy as np
from fastapi import FastAPI, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIP_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "ViT-B-16")
CLIP_MODEL_DIM = int(os.getenv("CLIP_MODEL_DIM", "512"))
MODEL_DIR = os.getenv("CLIP_MODEL_DIR", "/models/clip")
DEVICE = os.getenv("CLIP_DEVICE", "cuda")
MAX_BATCH = int(os.getenv("CLIP_MAX_BATCH", "64"))


class _ClipModel:
    def __init__(self) -> None:
        self.model = None
        self.preprocess = None
        self.device = DEVICE
        self.initialized = False

    def initialize(self) -> None:
        if self.initialized:
            return
        import torch
        from cn_clip.clip import load_from_name

        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA unavailable, falling back to CPU")
            self.device = "cpu"

        logger.info(
            "Loading Chinese-CLIP %s on %s (download_root=%s)",
            CLIP_MODEL_NAME,
            self.device,
            MODEL_DIR,
        )
        self.model, self.preprocess = load_from_name(
            CLIP_MODEL_NAME,
            device=self.device,
            download_root=MODEL_DIR,
        )
        self.model.eval()
        self.initialized = True
        logger.info("Chinese-CLIP ready")

    @staticmethod
    def _normalize(features) -> List[List[float]]:
        import torch

        features = features / features.norm(dim=-1, keepdim=True)
        return features.detach().cpu().numpy().astype(np.float32).tolist()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import torch
        from cn_clip.clip import tokenize

        tokens = tokenize(texts).to(self.device)
        with torch.no_grad():
            features = self.model.encode_text(tokens)
        return self._normalize(features)

    def embed_images(self, image_bytes_list: List[bytes]) -> List[List[float]]:
        import torch

        images = []
        for raw in image_bytes_list:
            try:
                image = Image.open(io.BytesIO(raw)).convert("RGB")
            except Exception as exc:
                raise ValueError(f"invalid image: {exc}") from exc
            images.append(self.preprocess(image))

        vectors: List[List[float]] = []
        with torch.no_grad():
            for start in range(0, len(images), MAX_BATCH):
                batch = torch.stack(images[start : start + MAX_BATCH]).to(self.device)
                features = self.model.encode_image(batch)
                vectors.extend(self._normalize(features))
        return vectors


clip_model = _ClipModel()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start = time.time()
    clip_model.initialize()
    logger.info("CLIP service started in %.1fs", time.time() - start)
    yield


app = FastAPI(title="CaliperGT CLIP Embedding Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TextEmbedRequest(BaseModel):
    texts: List[str]


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    vectors: List[List[float]]


@app.get("/health")
async def health() -> dict:
    return {
        "status": "healthy" if clip_model.initialized else "loading",
        "model": CLIP_MODEL_NAME,
        "dimensions": CLIP_MODEL_DIM,
        "device": clip_model.device,
    }


@app.post("/embed/text", response_model=EmbedResponse)
async def embed_text(request: TextEmbedRequest) -> EmbedResponse:
    if not request.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty")
    try:
        vectors = clip_model.embed_texts(request.texts)
    except Exception as exc:
        logger.exception("text embedding failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return EmbedResponse(
        model=CLIP_MODEL_NAME, dimensions=CLIP_MODEL_DIM, vectors=vectors
    )


@app.post("/embed/images", response_model=EmbedResponse)
async def embed_images(images: List[bytes] = File(...)) -> EmbedResponse:
    if not images:
        raise HTTPException(status_code=400, detail="no images uploaded")
    try:
        vectors = clip_model.embed_images(images)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("image embedding failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return EmbedResponse(
        model=CLIP_MODEL_NAME, dimensions=CLIP_MODEL_DIM, vectors=vectors
    )
