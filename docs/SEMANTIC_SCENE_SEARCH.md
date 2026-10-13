# 场景语义检索（Chinese-CLIP 图像向量）

在第一步「结构化标签统计检索」（`GET /api/v1/scenes/search`）之外，第二步提供
基于图像内容的语义检索：用一句自然语言（中文/英文）直接搜“汽车场景 / 二轮车场景 /
行人过马路”这类无法用类别枚举完整表达的需求。

## 架构

- `anno-clip`：独立 GPU 微服务，Chinese-CLIP `ViT-B-16`（OFA-Sys），512 维，
  与 SAM2 微服务同样的部署模式；代码见
  `backend/app/services/clip_gpu_service.py`，镜像见 `backend/Dockerfile.clip`。
- 后端无 torch，通过 HTTP 调用：`backend/app/services/clip_client_service.py`。
- 向量存 Postgres + pgvector 表 `frame_image_embeddings`
  （HNSW + `vector_cosine_ops`，迁移 `037_frame_image_embeddings.py`）。
- 检索与场景聚合：`backend/app/services/scene_semantic_search_service.py`。
  先做帧级最近邻，再按场景对该场景 top-K 帧的相似度取平均，得到场景分。

## 启动服务

```bash
cd caliperai-gt
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
  -f docker-compose.clip.yml up -d clip
```

首次启动自动从 hf-mirror 下载 Chinese-CLIP ViT-B-16 权重到 `clip_models` 卷。

## 回填图像向量

在后端容器内运行（可断点续跑，已存在的帧/相机会跳过）：

```bash
# 前视相机全部帧（约 50 img/s @ RTX 4090）
docker exec -e PYTHONPATH=/app anno-backend sh -c \
  'cd /app && CLIP_API_URL=http://clip:8002 \
   python scripts/backfill_frame_embeddings.py --cameras front'

# 全部 6 路相机
docker exec -e PYTHONPATH=/app anno-backend sh -c \
  'cd /app && CLIP_API_URL=http://clip:8002 \
   python scripts/backfill_frame_embeddings.py --cameras all'

# 快速抽样验证：前视、每 10 帧取 1 帧、最多 500 帧
... backfill_frame_embeddings.py --cameras front --stride 10 --limit 500
```

相机键兼容两种导入批次：标准名（`front`）与原始名（`camera_0_front100`）。

## API

- `GET /api/v1/scenes/search/semantic?q=...`
  - `q`：自然语言，如 `摩托车和自行车等二轮车场景`、`高速上的卡车和大巴`
  - `min_similarity`：阈值（默认 0.18；调试可传 0 看全量排序）
  - `top_k_frames`：每场景参与打分的帧数（默认 200）
  - `candidate_pool`：ANN 候选数；默认全量精确扫描（9k 帧约 250ms）
  - `cameras`、`dataset_id`、`page_size`
  - 返回每场景 `score`、`max_similarity`、`matched_frames`、`preview_frames`
- `GET /api/v1/scenes/embeddings/coverage`：各场景向量覆盖情况

需要 `scenes:read` 权限，与其他场景接口一致。

## 与第一步的选择建议

- 明确类别/数量条件（“含 bus、二轮车占比>15%”）→ 用第一步结构化检索，
  确定、可解释、零模型成本。
- 开放式视觉语义（“雨天夜间停车场”“施工路段”）→ 用本语义检索。
- 二者可叠加使用，例如先用语义检索找候选，再用标签统计做精确过滤。
