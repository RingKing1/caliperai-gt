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

## 混合检索（推荐主入口）

`GET /api/v1/scenes/search/hybrid` 在一个接口里串起两层：

1. **第一层 · 标签过滤**：按标注统计精确圈定候选场景（可解释、确定）。
2. **第二层 · 向量排序**：仅在候选集内用 Chinese-CLIP 对
   “堵车 / 雨夜路口 / 施工路段”等无法用类别表达的语义做排序。

参数同时包含两层：

- 标签层：`q`、`classes`、`groups`、`min_objects`、`min_class_ratio`、
  `min_group_ratio`、`min_group_frame_ratio`、`dataset_id`、`name_contains`
- 语义层：`semantic_q`、`cameras`、`min_similarity`、`top_k_frames`、
  `candidate_pool`、`preview_frames`
- 省略 `semantic_q` 时退化为纯结构化检索（`mode=structured`）。

返回的每个场景同时带：

- `matched_reasons` / `label_match_score` / `label_profile`：命中了哪些标签条件、
  各类与分组的数量和占比（可解释）；
- `semantic_score` / `max_similarity` / `matched_frames` / `preview_frames`：
  CLIP 语义分和代表帧。

示例：

```bash
# 只在“二轮车占比>=10%”的场景里，按“堵车”语义排序
curl -G .../api/v1/scenes/search/hybrid \
  --data-urlencode "q=二轮车" \
  --data-urlencode "min_group_ratio=0.10" \
  --data-urlencode "semantic_q=堵车的城市道路" \
  --data-urlencode "cameras=front"
```

不满足标签阈值的场景会在向量排序前被排除，因此兼顾准确率与可解释性。
