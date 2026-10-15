# GPU 微服务

独立部署的 FastAPI 进程：不装进主后端镜像、不导入 `app.services`，只与后端共享
线模型（Pydantic schema），避免双份维护。

```
microservices/
├── sam2/
│   ├── service.py        # SAM2 图像/视频分割推理（默认 :8001）
│   ├── Dockerfile        # NVIDIA CUDA 镜像（GPU）
│   └── Dockerfile.cpu    # python:3.11-slim（CPU/MPS）
└── clip/
    ├── service.py        # Chinese-CLIP 文本/图像 embedding（默认 :8002）
    └── Dockerfile        # 复用 SAM2 GPU 镜像层加 cn_clip
```

## 与后端共享的 schema

| 微服务 | 共享模块（canonical，主仓库内） | 微服务内的薄子类（仅契约增量） |
| :--- | :--- | :--- |
| sam2 | `backend/app/schemas/sam2.py` | `multimask_output`、`mask_index`、必填 `embedding_key` 收窄 |
| clip | `backend/app/schemas/clip.py` | 无，直接使用 |

构建上下文为仓库根目录，Dockerfile 只 COPY 需要的 schema 叶子模块进镜像：

```
COPY backend/app/__init__.py        /app/app/__init__.py
COPY backend/app/schemas/__init__.py /app/app/schemas/__init__.py
COPY backend/app/schemas/sam2.py    /app/app/schemas/sam2.py
```

## 启动方式

```bash
# SAM2 GPU
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d sam2
# SAM2 CPU（无 NVIDIA 显卡）
docker compose -f docker-compose.yml -f docker-compose.sam2.yml up -d sam2
# CLIP GPU（依赖已构建的 caliperai-gt-sam2 镜像）
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
  -f docker-compose.clip.yml up -d clip
```

主后端通过 `SAM2_MODE=api` / `CLIP_API_URL` 调用这些进程；不启动时 SAM2 走
mock、CLIP 语义检索不可用，主服务其余功能不受影响。

## 修改线模型的注意事项

字段变更只需改 `backend/app/schemas/` 下的 canonical 模块并重新构建微服务镜像；
微服务端到端的请求/响应契约（含薄子类的增量字段）由
`microservices/sam2/service.py` 与 `microservices/clip/service.py` 的 FastAPI app
承载。SAM2 微服务的模型类名保留历史命名（`PointPrompt` 等），与后端代理 API 的
`*Schema` 命名通过 import 别名对齐。
