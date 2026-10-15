# Chinese-CLIP GPU microservice, built on the existing SAM2 GPU image
# (already contains torch 2.5.1 + CUDA 12.1, fastapi, uvicorn, pillow).
ARG SAM2_IMAGE=caliperai-gt-sam2:latest
FROM ${SAM2_IMAGE}

RUN pip install --no-cache-dir tqdm six "timm>=0.9,<1.0" \
    && pip install --no-cache-dir --no-deps "cn_clip==1.6.0"

WORKDIR /app
# Wire schemas shared with the backend, then the CLIP service
COPY backend/app/__init__.py /app/app/__init__.py
COPY backend/app/schemas/__init__.py /app/app/schemas/__init__.py
COPY backend/app/schemas/clip.py /app/app/schemas/clip.py
COPY microservices/clip/service.py /app/clip_gpu_service.py

ENV CLIP_MODEL_NAME=ViT-B-16
ENV CLIP_MODEL_DIM=512
ENV CLIP_DEVICE=cuda
ENV CLIP_MODEL_DIR=/models/clip
ENV PYTHONUNBUFFERED=1

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=10 \
    CMD python3 -c "import httpx; r=httpx.get('http://localhost:8002/health'); r.raise_for_status(); assert r.json()['status']=='healthy'" || exit 1

CMD ["python3", "-m", "uvicorn", "clip_gpu_service:app", "--host", "0.0.0.0", "--port", "8002"]
