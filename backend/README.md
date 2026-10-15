# CaliperAI-GT 后端架构设计与开发文档

面向自动驾驶 4D 多模态数据闭环标注平台的后端服务。提供数据集 / 场景 / 任务工作流、
2D / 3D / 4D / 融合 / 分割多模态标注、QA 审核、效率看板、SAM2 分割与 RAG 智能助手等能力。

> 前端架构见 [`../frontend/README.md`](../frontend/README.md)。本文档描述后端当前的
> **真实**架构：既包括已落地的分层规范，也在文末明确列出尚未完成的重构项。

---

## 1. 技术栈

| 领域 | 选型 | 说明 |
| :--- | :--- | :--- |
| Web 框架 | FastAPI + Uvicorn/Gunicorn | 异步 ASGI，生产用 UvicornWorker |
| ORM | SQLAlchemy 2.x async (`AsyncSession`) | `Mapped` 类型化声明式模型 |
| 数据库 | PostgreSQL + pgvector | JSONB、INT4RANGE 帧范围、向量检索 |
| 迁移 | Alembic（16 个版本） | 与启动期 `create_all` 双轨并存 |
| 校验 | Pydantic v2 | 请求 / 响应 schema 与 OpenAPI |
| 缓存 | Redis | embedding 缓存等 |
| 对象存储 | MinIO（S3 兼容）/ GCS | 按组织分桶 + 预签名 URL |
| AI | SAM2、CLIP、Ollama LLM | 主服务通过 HTTP 调用独立 GPU 微服务 |
| 鉴权 | JWT + OIDC/SSO | 自研 RBAC 依赖注入 |

规模：31 个 endpoint 模块、226 个路径 / 278 个操作、24 个 service 模块。

---

## 2. 目录结构

```text
backend/
├── app/
│   ├── main.py                  # FastAPI 入口：lifespan、中间件、全局异常处理、路由挂载
│   ├── api/v1/
│   │   ├── router.py            # 聚合所有 endpoint 子路由（唯一注册点）
│   │   └── endpoints/           # HTTP 控制器层（31 个模块，按业务域拆分）
│   ├── services/                # 业务 / 集成服务层
│   │   ├── dataset_import/        # ★ 导入域服务包（解析/标定/发现/分类法/存储/落库，见 §12）
│   │   ├── annotation_service.py   # ★ 跨模态标注写路径统一业务层（参考范式）
│   │   ├── task_service.py         # ★ 标注任务域：生命周期/查询/编辑器引导（见 §12）
│   │   ├── qa_service.py           # ★ 质检域：评审会话/逐条判定/评论/建议（见 §12）
│   │   ├── dataset_service.py      # ★ 数据集域：CRUD/分类法挂接/任务自动创建（见 §12）
│   │   ├── scene_service.py        # ★ 场景域：CRUD/检索参数解析/帧取图定位（见 §12）
│   │   ├── efficiency/             # ★ 效率域服务包（8 个子域全部迁入，见 §12）
│   │   ├── workflow_service.py     # 任务阶段/状态状态机
│   │   ├── rbac_service.py         # JWT 校验 + 权限/角色依赖
│   │   ├── sam2_service.py         # SAM2 客户端（mock / 调远程 GPU 服务）
│   │   ├── sam2_gpu_service.py     # ⚠ 独立部署的 FastAPI GPU 微服务（非领域服务）
│   │   ├── clip_gpu_service.py     # ⚠ 独立部署的 CLIP embedding GPU 微服务
│   │   ├── chat_service.py / llm_service.py / knowledge_service.py
│   │   ├── scene_*_search_service.py  # 结构化 / 语义 / 混合场景检索
│   │   └── storage_service.py / gcs_service.py / sso_service.py ...
│   ├── models/                  # ORM 模型包（base/enums + efficiency/org/user 已拆出，见 §12）
│   │   ├── base.py              # Base 重导出 + TimestampMixin/SoftDeleteMixin
│   │   ├── enums.py             # 全部枚举 + ROLE_PERMISSIONS（随域迁移）
│   │   ├── org.py / user.py     # 组织成员 / 用户与 SSO
│   │   ├── catalog.py           # 分类法/活动/数据集 + 关联表
│   ├── schemas/schemas.py       # ⚠ 单文件 180+ 个 Pydantic 模型（待分包）
│   └── core/                    # 基础设施
│       ├── config.py            # pydantic-settings 配置（强制强 SECRET_KEY）
│       ├── database.py          # engine / session / get_db / init_db
│       ├── redis_cache.py       # Redis 连接生命周期
│       ├── file_security.py     # 上传路径穿越防护、magic byte 校验
│       └── prompts.py           # LLM 提示词
├── alembic/                     # 数据库迁移
├── tests/                       # pytest（asyncio_mode=auto）
├── scripts/                     # 运维脚本（建管理员、回填、初始化等）
├── knowledge_base/              # RAG 文档源
├── Dockerfile                   # base / builder / production / development 多阶段
├── gunicorn.conf.py             # 生产 WSGI/ASGI 配置
└── pyproject.toml
```

---

## 3. 分层架构与请求生命周期

```mermaid
flowchart TD
    Client["前端 (React Query → api/client.ts)"]
    subgraph HTTP["HTTP 控制层 app/api/v1/endpoints"]
        EP["薄 endpoint<br/>鉴权依赖 / 参数校验 / 404·400 映射 / 响应模型"]
    end
    subgraph Domain["业务层 app/services"]
        ANN["annotation_service ★"]
        WF["workflow_service"]
        OTHER["rbac / organization / chat / search ..."]
    end
    subgraph Infra["数据与基础设施"]
        DB[("PostgreSQL")]
        REDIS[("Redis")]
        MINIO["MinIO / GCS"]
        GPU["SAM2 / CLIP GPU 微服务"]
    end

    Client -->|/api/v1/*| EP
    EP --> ANN
    EP --> WF
    EP --> OTHER
    ANN --> WF
    ANN --> DB
    WF --> DB
    OTHER --> DB
    OTHER --> REDIS
    OTHER --> MINIO
    OTHER --> GPU
```

一个请求的标准生命周期：

1. **中间件**：GZip 压缩 → CORS。
2. **路由**：`app/main.py` 把 `api_router` 挂在 `/api/v1` 前缀下，子路由在
   `api/v1/router.py` 统一注册。
3. **鉴权依赖**：`Depends(get_current_user)` 或
   `Depends(RequirePermissions(Permission.XXX))` 完成 JWT 解析与 RBAC 校验。
4. **会话依赖**：`db: AsyncSession = Depends(get_db)` 提供请求级事务
   （成功自动 commit，异常自动 rollback，见 §5）。
5. **业务逻辑**：endpoint 调用 service；service 持有业务规则与数据访问。
6. **响应**：用 `response_model=` 序列化，`redirect_slashes=False`，URL 必须精确匹配。
7. **未捕获异常**：`main.py` 的全局 handler 记录完整堆栈但只返回通用 500，
   `HTTPException` 透传保留正确状态码。

启动期 `lifespan`：`init_db()`（PostgreSQL advisory lock 串行化 `create_all`）→
`init_redis()` → RAG 索引初始化（可开关）→ 性能告警后台任务。

---

## 4. 核心编码规范：薄 endpoint → service 层

### 4.1 为什么

历史代码大部分数据访问直接写在 endpoint 中（当前仍有约 590 处 DB 操作在
`endpoints/` 内），导致同一条业务规则在多个文件复制粘贴、各自漂移。标注域已完成
重构，是后续所有业务域的**参考范式**。

### 4.2 参考实现：`AnnotationService`

`app/services/annotation_service.py` 统一了五种标注表（generic / 2D / 3D / 4D /
fusion）的写路径规则：

- **任务自动流转**：首次写入时把 `pending/assigned` 的任务转为 `in_progress`，
  非法流转静默跳过（`maybe_start_work`）；批量写入按 task 去重只流转一次。
  此前该逻辑在 5 个 endpoint 中各复制了一份且签名已漂移，现已零副本。
- **`is_verified` 推导**：`resolve_is_verified(source, modality, explicit)` 是唯一
  事实源——人工来源（`manual` / `manual_2d` / `manual_3d` / `manual_fusion`）默认视为
  已人工确认；客户端显式传值优先（如插值帧显式存为未确认）。2D / 3D 的单条与批量
  upsert 现在共用同一条规则。
- **ORM 构造 / upsert 映射**：`build_2d/3d/4d/fusion/generic`、`apply_2d/3d`
  封装字段映射、4D 的 frame UUID→str 归一化、fusion 的 `data_2d` 投影模型归一化。

### 4.3 endpoint 应当长什么样

```python
@router.post("/", response_model=Annotation3DResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation_3d(
    annotation: Annotation3DCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
):
    service = AnnotationService(db)                       # 业务层
    task = await service.get_task(annotation.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")   # HTTP 映射留在这里
    if not await service.get_frame(annotation.frame_id):
        raise HTTPException(status_code=404, detail="Frame not found")

    await service.maybe_start_work(task, current_user.id)
    db_annotation = await service.create_3d(annotation)   # 规则在 service

    try:
        await check_achievements_for_user(db, current_user.id)
    except Exception as exc:
        logger.warning("Achievement check failed after 3D create: %s", exc)
    return db_annotation
```

### 4.4 新代码 checklist

- endpoint 只做：鉴权依赖、参数/Pydantic 校验、调用 service、HTTP 异常映射、声明
  `response_model`。**不要**在 endpoint 里写 `select()` / `db.add()` / 业务规则。
- service 不 import FastAPI、不抛 `HTTPException`，用普通异常或返回 `None`，
  由 endpoint 决定 HTTP 语义；这样业务规则可以脱离 HTTP 做单测。
- 跨多个 endpoint 复用的规则必须收敛到 service，禁止再复制粘贴 helper。
- 批量接口在 service 内对“任务自动流转”等副作用做幂等去重。
- 新增业务规则时同步在 `tests/` 补 service 级单测（参考
  `tests/test_annotation_service.py`）。

### 4.5 为前端请求瀑布设计的聚合端点

前端 `useTaskDataLoader` 原先需要 task → scene → dataset → taxonomies → primary →
selected 的多次串行请求。现提供单一聚合端点：

```text
GET /api/v1/tasks/{task_id}/editor-context
→ { task, scene, dataset, taxonomies, primary_taxonomies, selected_taxonomy }
```

- 可见性规则与 `GET /tasks/{id}` 完全一致（只能看分配给自己的任务，除非有
  `TASKS_READ_ALL` 权限）。
- `taxonomies` 的来源 / 排序与 `GET /datasets/{id}/taxonomies` 一致；
  `primary_taxonomies` 采用严格 `is_primary` 语义（与前端原 `primary_only=true` 一致）。
- 前端用 React Query 的 `setQueryData` 把聚合结果回填到各独立缓存键，其它组件无感复用。
- 新增聚合只读端点时遵循同样原则：**纯增量**，不替换或破坏既有细粒度端点。

---

## 5. 数据访问与事务

### 5.1 会话与事务边界

`core/database.py` 的 `get_db()` 是请求级依赖：

```python
async with async_session_factory() as session:
    try:
        yield session
        await session.commit()      # 请求正常结束 → 统一提交
    except Exception:
        await session.rollback()    # 任何异常 → 回滚
        raise
```

注意：部分历史 endpoint / service 在请求中途显式 `await db.commit()`（例如标注写路径）。
新代码应尽量依赖请求结束时的统一提交，减少中途 commit；改动既有代码时保持其原有提交
边界，避免无意的行为变化。

### 5.2 模型与 schema

- ORM：`models/models.py`（`Base(DeclarativeBase)` + `TimestampMixin` /
  `SoftDeleteMixin`）。软删除统一用 `is_deleted`，查询需显式过滤。
- 请求/响应：`schemas/schemas.py`，公共基类 `BaseSchema`。
- 枚举在 models 与 schemas 中各有定义，赋值前注意取 `.value`（`AnnotationService`
  的 `enum_value` 已封装这一点）。

### 5.3 迁移

- 目录：`alembic/versions/001_*` … `016_*`。
- 现状是双轨：启动时 `init_db()` 仍会 `create_all(checkfirst=True)`，同时存在 Alembic
  迁移。**新增表 / 列必须补 Alembic 迁移**；长期目标是生产只走 Alembic（见 §12）。

---

## 6. 认证与授权（RBAC）

`services/rbac_service.py` 提供 FastAPI 依赖：

- `get_current_user`：解析 Bearer JWT，返回 `User`。
- `RequirePermissions(*Permission.XXX, require_all=True)`：细粒度权限守卫，
  是绝大多数写接口的标准依赖。
- `RequirePermissionsWithQuery`：用于 token 走 query 参数的图片等场景。
- `RequireRole(*UserRole.XXX)`：按角色守卫。

`Permission` 枚举覆盖 campaigns / datasets / scenes / tasks / annotations /
taxonomies / users / QA / import 等资源的增删改查。新增接口必须挂对应权限依赖，
默认拒绝而非默认放行。

---

## 7. 基础设施与外部集成

- **配置**：`core/config.py` 用 `pydantic-settings` 从环境变量 / `.env` 读取；
  启动时强制校验 `SECRET_KEY` 强度，拒绝默认弱密钥。
- **Redis**：`core/redis_cache.py` 管理连接生命周期，service 通过 `get_redis()` 使用。
- **对象存储**：`storage_service.py` 按组织分桶（`org-{id}`），浏览器只拿预签名
  URL，管理凭证不下发；另有 `gcs_service.py`。
- **上传安全**：`core/file_security.py` 做路径穿越校验与 magic byte 校验；
  数据文件有 `DATA_EXTENSIONS` 白名单。
- **SSO/OIDC**：`sso_service.py` + `endpoints/sso.py`，支持 Google/Azure/Okta/
  Keycloak，邮箱域名→组织映射。

### AI 能力

| 模块 | 形态 |
| :--- | :--- |
| `sam2_service.py` | 主服务内的客户端，按 `SAM2_MODE` 在 mock 与远程服务间切换，带 embedding 缓存 |
| `sam2_gpu_service.py` | **独立 FastAPI 进程**（默认 :8001），持 GPU 跑 SAM2 |
| `clip_client_service.py` / `clip_gpu_service.py` | CLIP 客户端与独立 embedding GPU 进程 |
| `llm_service.py` / `chat_service.py` | Ollama LLM 接入与多轮对话 |
| `knowledge_service.py` / `semantic_chunker.py` / `embedding_service.py` | RAG：分块、embedding、检索增强 |
| `scene_search_service.py` / `scene_semantic_search_service.py` / `scene_hybrid_search_service.py` | 结构化标签检索、CLIP 语义检索、混合排序 |

---

## 8. REST API 地图（按 `router.py`）

| 前缀 | 模块 | 说明 |
| :--- | :--- | :--- |
| `/organizations` | organizations | 组织与成员 |
| `/auth`, `/auth/sso` | auth, sso | 登录、刷新、SSO 回调 |
| `/campaigns` `/datasets` `/taxonomies` `/scenes` | 同名 | 项目资源层级 |
| `/tasks` | tasks | 任务 CRUD、状态/阶段、`/tasks/{id}/editor-context` 聚合、frames、split、注入预测 |
| `/annotations` | annotations | 通用标注表（legacy） |
| `/annotations-2d` `/annotations-3d` `/annotations-4d` `/annotations-fusion` `/tracks-2d` | 同名 | 各模态标注，写路径统一走 `AnnotationService` |
| `/frames` `/data` `/gcs` | frames, data, gcs | 帧、点云/图像数据、存储代理 |
| `/qa` `/workflow` `/dataops` | qa, workflow, dataops | 审核流、状态机、数据运营快照 |
| `/import` | import_data, import_annotations | 数据集 / 标注导入（业务逻辑已下沉 `services/dataset_import/`，见 §12） |
| `/export` | export | 多格式导出 |
| `/sam2` `/segmentation` | sam2, segmentation | SAM2 交互分割、语义分割 |
| `/analytics` `/efficiency` | analytics, efficiency | 指标、计时、成就、告警、排行榜 |
| `/chat` `/knowledge` | chat, knowledge | LLM 助手与 RAG |
| `/users` | users | 用户管理 |

交互式文档：开发环境 `http://localhost:8000/api/docs`（生产环境关闭 docs/openapi）。
健康检查：`GET /health`。

---

## 9. 配置与本地开发

关键环境变量（完整列表见 `core/config.py` 与 `docker-compose.yml`）：

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export DATABASE_URL="postgresql+asyncpg://postgres:devpassword@localhost:5432/annotation_platform"
export REDIS_URL="redis://localhost:6379/0"
# OBJECT_STORAGE_*、SAM2_MODE、SAM2_API_URL、LLM_PROVIDER、OLLAMA_*、RAG_*、SSO_*
```

```bash
# 本地虚拟环境
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# 测试（pytest，asyncio_mode=auto）
pytest -q
```

---

## 10. 容器化与部署

- `Dockerfile` 多阶段：`base` → `builder` → `production`（默认，
  `gunicorn -c gunicorn.conf.py`）/ `development`（`uvicorn --reload`），
  通过 `BUILD_TARGET` 选择。
- **代码热重载**：`docker-compose.yml` 把 `./backend:/app` 挂载进容器。
  - development target：改代码自动 reload，无需重建镜像；
  - production target（gunicorn 无 reload）：改代码后 `docker compose restart backend` 即可，
    **无需重新 build 镜像**；只有改 `Dockerfile` / 依赖 / 基础镜像时才需要
    `docker compose build backend`。
- 生产 WSGI 参数见 `gunicorn.conf.py`：`TIMEOUT` 默认 7200s 以兼容大型数据集上传。
- SAM2 / CLIP GPU 服务另有 `Dockerfile.sam2*` / `Dockerfile.clip` 与独立 compose 文件。

---

## 11. 测试

- 框架：pytest + pytest-asyncio（`asyncio_mode = "auto"`）。
- 现有覆盖：JWT/SSO 安全、文件/浏览路径安全、密钥强度、MinIO 存储、场景检索、
  OpenAPI 文档，以及标注业务层 `test_annotation_service.py`。
- 业务规则测试优先针对 **service 层**（不需要起 HTTP / DB 即可覆盖构造与推导规则）。
- 当前共 257 个测试用例，改动后应保持全绿。

---

## 12. 重构现状与路线图（重要）

后端**尚未全部完成解耦重构**。标注域（本文 §4）已落地为标准范式，其余区域按以下
顺序推进，原则与前端 `FusionEditorV2` 重构一致：小步提取、零功能倒退、提取后即唯一事实源。

### 已完成

- [x] 统一跨模态标注业务层 `services/annotation_service.py`，收口 5 份
      `auto_transition` 副本与 `is_verified` 推导分叉（2D/3D、单条/批量规则统一）。
- [x] 五个标注 endpoint 瘦身为薄控制器。
- [x] `GET /tasks/{id}/editor-context` 聚合端点 + 前端 React Query 接入与缓存回填。
- [x] 标注 service 层单元测试。
- [x] **P0 导入域拆分**：新增 `services/dataset_import/` 包（13 个模块 / 约 3.6k 行）——
      `constants` / `schemas` / `calibration` / `naming` / `tasks` / `discovery` /
      `storage` / `taxonomy` / `scene_importer` / `annotation_parsers` /
      `annotation_pipeline`；`import_data.py` 3040→1694 行、
      `import_annotations.py` 2700→759 行，两个端点仅保留 11 个路由及其原有事务
      边界（URL / 响应模型零变化，跨层引用与测试同步切换，257 测试全绿）。
- [x] **P0 收尾（第一批）：上传管线特征测试 + 共用步骤提取**：
      新增 `tests/test_import_pipelines.py`（33 个测试）锁定 upload / upload-zip /
      upload-video 三条管线当前行为，并实测记录了一处分叉：`/upload` 把内部 400
      （路径穿越 / magic byte）吞成 500，zip 与 video 保留 400；提取
      `pipeline_layout`（场景发现 / 数据源分类）、`frame_rows`（Frame 行构建）、
      `storage.schedule_scene_mirror`（MinIO 镜像调度）三个共用件，upload/zip 的
      逐场景循环改为调用共用件（`import_data.py` 1694→1500 行），290 测试全绿。
- [x] **导入域历史告警清零 + `/import` 场景名 bug 修复**：清除拆分时平移保留的
      F821/F841/F541/F811 告警（未用变量、无占位符 f-string、重复局部导入）；
      其中 F821 是真实潜在 bug——本地文件夹导入路由 `POST /import` 使用了从未定义的
      `scene_name`，导致每个场景都抛 `NameError` 被 except 吞掉而导入失败，现改为
      `scene_meta.get("name") or scene_dir.name`，并补 3 个回归测试（293 测试全绿）。
- [x] **上传管线错误码对齐**：`/upload` 增加 `except HTTPException: raise`，
      文件校验类 400（路径穿越 / magic byte）不再被宽异常吞成 500，与 zip/video 一致。
- [x] **zip 管线 `storage_paths` 超集对齐（2a）**：zip 导入补齐 `root` /
      `images_base` / `ego_poses` 三个键（此前缺失会导致 `tasks.py` 与 `export.py`
      读 `root` 退化），`ego_poses` 记录相对存储键；同时修正 zip 构造 Scene 时漏传
      `id=scene_id` 导致落盘目录 UUID 与数据库主键不一致的问题。新增 ego_pose 键与
      6 相机布局两管线对等测试（295 测试全绿），并用真实 6 相机 10 帧 ZIP 实测
      upload / zip 两条管线产出一致（10 帧 × 6 相机、6 路标定、10 个 KITTI 标注就位）。
- [x] **frames 路由遮蔽 + 回退布局取图历史问题修复**：`create_frames_bulk` 原误写为
      `GET ""` 且排在 `list_frames` 前，遮蔽所有 `GET /frames?scene_id=`（422），现改为
      `POST /frames/bulk`。取图端点 `GET /scenes/{id}/frames/{idx}/image` 的路径解析
      硬编码 `<scene>/cameras/<cam>/`，且场景根靠“主文件是 lidar”的假设（`parent.parent`）
      推导，导致 images/ 与平铺回退布局必然 404（无 lidar 的纯相机标准布局同样受影响）；
      同时 `FrameFilePaths.lidar` 必填使纯图像帧的 `GET /frames` 响应校验直接 500。
      现解析器按 `_meta.relative_path` 深度推导场景根，依次尝试 cameras / images / 场景根
      三种位置；单相机场景任意相机别名（含默认 `front`）均可取到唯一图像；`lidar` 改为可选。
      补 3 个路由表测试与 12 个解析器回归测试，真实环境验证 images / 平铺 / 6 相机三种布局
      取图与 `GET /frames` 均正常（304 测试全绿，容器内 6 个 minio 基线 error 为既有项）。

### 待完成（按 ROI 排序）

- [x] **P0 收尾（2b/2c）：抽取共享逐场景 orchestrator**：`/upload` 与 `/upload-zip`
      的逐场景循环（原各约 250 行）合并为
      `services/dataset_import/scene_pipeline.py` 的 `import_one_scene`，
      `import_data.py` 从 1497 行降至 1051 行。历史分叉不再散落在两份循环里，而是显式
      收敛到 `PipelineSpec`：ego pose（upload 从父级 metadata.json 合成 / zip 支持
      JSON list）、标定继承（upload 逐场景重置 / zip 继承数据集级标定）、重名检查
      （zip 对用户改名跳过）、回退布局归类（upload 单合成相机 / zip 的 images、default、
      lidar 分桶）、场景元数据字段约定。新增 6 个分叉语义单测；真实验证：同一真实 6 相机
      10 帧 ZIP 分别走 upload 与 zip 两条管线，均产出 10 帧 × 6 相机、6 路标定、130 个
      3D 标注、MinIO 82 对象且 storage_paths 五键对等（310 测试全绿，容器内 6 个 minio
      基线 error 为既有项）。**分叉的“语义口径统一”（是否要让两管线行为真的一致）仍
      需逐项确认**：ego 合成、数据集级标定继承、改名跳查重、相机键命名等分叉仍按原样
      保留；video 管线结构不同，未并入。
- [x] **upload 管线 images/ 回退布局相机 base 对齐 zip**：upload 把 images/ 子目录场景
      归为单相机时，`storage_paths.cameras` 的 base 误写为场景根（文件实际在 `images/`
      子目录），前端按 `{base}/{filename}` 拼出的 `/data/image` URL 必然 404；zip 管线
      写的是 `…/images` 本就正确。现 upload 检测到帧文件全部位于 `images/` 时 base
      追加 `/images`，松散平铺文件仍用场景根（不回归）。补 2 个单测，真实 multipart
      上传两种布局复验前端取图 URL 均 200（312 测试全绿）。注意：修复前已入库的旧场景
      仍带错误 base，需要时按 `images_base` 做一次性数据订正。
- [x] **P0 收尾（3）：长上传后台 job 化**：新增 `import_jobs` 表（模型 +
      Alembic 038 迁移）与 `POST /import/jobs/zip`、`POST /import/jobs/upload`
      两个 202 端点；接收 worker 落盘 staging 后写入 pending job，由本进程
      `asyncio.create_task` 执行解压/导入，进度用独立短事务写入，多 gunicorn worker
      下任意 worker 均可轮询 `GET /import/jobs/{id}`、`GET /import/jobs?dataset_id=`。
      导入仍保持原有单事务提交（不会出现半导入可见）；staging 临时目录由 job 收尾清理。
      同步端点 `/import/upload`、`/import/upload-zip` 保留可用，内部统一改调
      `execute_directory_import`（staging 之后的扫描/标定/分类法/逐场景/提交内核）。
      前端 ZIP 改为“网络上传 0-50% + 后台处理 50-100%”分段进度，文件夹上传提交后轮询；
      浮动上传队列显示中文阶段（排队/解压/扫描/导入/保存）。新增 6 个 job 测试，
      318 测试全绿，真实 82MB 10 帧 6 相机 ZIP 实测：202 秒回、轮询跑完
      10 帧/6 相机/130 标注，staging 零残留。已知边界：worker 进程被杀死时 running job
      不会自动接管（表中有 heartbeat_at，后续可加超时回收）；video 入口未 job 化。
- [x] **P1（1/5）标注任务域提取 `task_service`**：`endpoints/tasks.py`
      829 → 217 行薄端点（鉴权 + HTTP 映射），全部生命周期 / 查询 / editor-context
      逻辑平移到 `services/task_service.py`（810 行）。领域异常
      `TaskNotFoundError` / `TaskForbiddenError` / `TaskValidationError`
      （不继承 HTTPException），端点统一映射 404/403/400；纯规则
      `frame_range_to_postgres` / `compute_frame_window` / `VALID_TRANSITIONS` /
      `revision_reset_reason` / `is_task_participant` 可脱离 DB 单测。
      `dataset_import/tasks.py` 复用同一份 `frame_range_to_postgres`（经
      `dataset_import` 包重导出保持旧 import 路径可用）；`SubTaskRequest` /
      `SplitTaskRequest` 从端点内联模型归位 `schemas.py`。新增 9 个纯规则单测
      （327 测试全绿），真实数据冒烟 list / editor-context / frames / stats /
      404 / split 400 全部通过；URL、响应模型、PATCH 三分支重置语义零变更。
- [x] **P1（2/5）质检域提取 `qa_service`**：`endpoints/qa.py` 1018 → 369 行
      薄端点，23 个路由（评审会话 / 逐条标注判定 / 评论 / AI 建议 / 统计）
      全部下沉 `services/qa_service.py`（940 行）。领域异常
      `QANotFoundError` / `QAValidationError` 统一映射 404/400；纯规则
      `next_stage_after_qa`（QA→客户质检/验收、客户质检→验收）与
      `sort_suggestions`（severity 排序，未知级别按 medium）脱离 DB 可单测，
      新增 7 个单测（334 测试全绿）。OpenAPI 23 路由方法/路径零差异，真实数据
      冒烟通过。顺带修复历史 bug：`POST /qa/annotation-reviews/{id}/resolve`
      对不存在记录引用了未导入的 `status` 常量，原行为是 500 NameError，现正确
      返回 404；成功路径行为不变（manual suggestion 仍保持其原有 commit 语义）。
- [x] **P1（3/5）数据集域提取 `dataset_service`**：`endpoints/datasets.py`
      619 → 241 行薄端点，11 个路由（数据集 CRUD、内嵌/关联分类法、挂分类法自动
      建任务、变体数据集）全部下沉 `services/dataset_service.py`（537 行）。
      领域异常区分 404（Dataset/Campaign/Taxonomy）/409（重名）/400（重复挂接、
      无分类法）；纯规则 `compute_dataset_stats` 与 `make_scene_taxonomy_task`
      可脱离 DB 单测，新增 4 个单测（338 测试全绿）。`auto_create_tasks_for_scene`
      迁入 service 并在端点模块重导出，`scene_pipeline` / `scenes` / `import_data`
      三个调用方改从 service 导入（顺带消除 scene_pipeline 的 service→endpoint
      反向依赖，并清掉这些文件原有的 ruff 导入排序/未用导入告警）。OpenAPI 11 条
      路由契约零差异，真实数据集 detail/taxonomy/taxonomies 冒烟通过。
- [x] **P1（4/5）场景域提取 `scene_service`**：`endpoints/scenes.py`
      621 → 345 行薄端点，9 个路由（场景 CRUD/标定、标签检索/混合检索/语义检索/
      embedding 覆盖度、帧相机取图）的业务逻辑下沉 `services/scene_service.py`。
      检索打分仍留在专门的 `scene_*_search_service`，新 service 只负责 query
      参数解析与响应整形；纯规则 `split_filter_values` / `parse_label_filters`
      （类名归一化、group 别名解析、非法 group 抛结构化 400）脱离 DB 可单测；
      帧取图拆为“service 解析磁盘路径（404 决策）+ 端点 PIL 缩略图/流式响应
      （表现层）”。`_resolve_frame_image_path` 迁入 service 并在端点保留旧名
      重导出，内联模型 `SceneSearchResponse` 归位 `schemas.py`（OpenAPI 组件名
      与 9 条路由契约零差异）。领域异常 Scene/Dataset(复用数据集域)/Frame/
      Conflict/Validation 分层映射，新增 6 个单测（344 测试全绿），真实数据
      检索与帧缩略图冒烟通过。
- [x] **P1（5/N）效率域按子域续拆（建包 + sessions）**：`endpoints/efficiency.py`
      是 2428 行 / 27 路由的最大单文件，本次先建 `services/efficiency/` 包
      （`errors.py` 领域异常、`schemas.py` 内联 30 个请求/响应模型整体归位、
      `common.py` 匿名别名/显示名/每日统计），并完成第一个子域 **sessions**：
      7 个任务计时/登录会话路由改薄端点，业务逻辑入 `sessions.py`
      （180s 空闲阈值、心跳 active/idle 计时、会话结束写日统计/任务总时长等
      语义零变更）。领域异常 NotFound/Forbidden/Validation 映射 404/403/400；
      新增 3 个 `generate_alias` 单测（347 测试全绿），OpenAPI 7 条会话路由与
      组件 schema 零差异。其余子域（activity/goals/achievements/alerts/
      challenges/stats/reports）见后续提交，效率域已全部拆分完成。
- [x] **P1（5/N）效率域 activity + goals 子域**：新增包内
      `activity.py`（单条/批量事件，含任务会话计数联动）与 `goals.py`
      （目标 CRUD + 标注量实时进度，`count_labels_in_period` 五表统计与
      自动来源过滤迁入，纯规则 `_progress_percentage` 单测覆盖）；端点新增
      6 条薄路由（351 测试全绿；顺带清掉 efficiency.py 基线全部 F401 死
      导入，仅保留历史 F841），OpenAPI 契约零差异。
- [x] **P1（5/N）效率域 achievements + alerts 子域**：`achievements.py`
      承载成就展示元数据 `ACHIEVEMENT_INFO`、我的/未读列表、标记已见
      （纯函数 `achievement_display` 统一标题/描述/图标回退，2 个单测）；
      `alerts.py` 承载团队绩效告警列表（显示名组织脱敏联动）与确认。
      5 条端点改薄路由（353 测试全绿），404/403 经领域异常映射，
      OpenAPI 契约零差异。**剩余**：个人 stats、live/team、team-stats、
      leaderboard（约 700 行聚合）、team-member-report。
- [x] **P1（5/N）效率域 challenges 子域**：`challenges.py` 承载团队挑战
      列表（实时五表标注量进度、top5 贡献者、完成态自动翻转）、创建
      （无组织时回查成员关系，缺失抛 400）、更新/删除（创建者或 admin 授权，
      403 领域异常）；`compute_challenge_progress` 与自动来源过滤一并迁入，
      纯规则进度百分比补 2 个单测，4 条端点改薄路由（354 测试全绿，
      OpenAPI 契约零差异）。端点文件从 2428 行降至约 1100 行；仅剩个人/团队
      stats、live、leaderboard、team-member-report 五个大聚合路由待拆。
- [x] **P1（5/N）效率域 stats + reports 子域（P1 收尾）**：新增 `stats.py`
      承载个人统计、团队实时状态、team-stats 大聚合、排行榜 4 条路由，
      `reports.py` 承载 team-member-report CSV 报告导出；纯规则抽为
      `team_period_start` / `leaderboard_period_start` / `build_quality_metrics`
      / `throughput_metrics` / `resolve_active_time` / `format_duration`
      并补 10 个单测。五表统计与自动来源过滤统一复用模块常量，report
      原 `HTTPException(404)` 改抛 `EfficiencyNotFoundError` 由端点映射；
      顺带清除仅服务于死变量 `start_date` 的 F841 及其死时间取值。
      端点 1315 → 481 行（全域 2428 → 481），5 条薄路由，365 测试全绿，
      真实数据冒烟 200/200/200/200/404，OpenAPI 27 个 operation 与组件
      schema 零差异。**P1 五个业务域全部完成**。
- [~] **P2 模型 / schema 分包（进行中，1/N）**：目标是把 `models/models.py`
  （3627 行 / 60 类）按域拆入 `models/` 包（org、user、catalog、scene、task、
      annotation、qa、efficiency、chat），`models.py` 保留为门面重导出，保证
      67 处 `from app.models.models import X` 与 alembic/env.py 零改动。
      已完成基础设施 + efficiency 域：`base.py`（Base 重导出 + 两个 Mixin）、
      `enums.py`（效率域 5 枚举）、`efficiency.py`（9 类：TimeSession /
      UserLoginSession / ActivityEvent / UserGoal / Achievement / PerformanceAlert
      / DailyUserStats / TeamChallenge / ChallengeParticipant），models.py
      3627 → 2917 行。跨域引用全部是字符串 relationship/ForeignKey，无运行时
      循环（跨域类型仅 TYPE_CHECKING 导入）；40 张表的 `CreateTable` DDL 与
      拆分前逐字节一致，365 测试全绿，真实 DB 冒烟全 200，新文件 E/F/I/N/W
      零告警（清掉历史 Geometry 死导入 F401）。每片做一次 DDL 逐字节核对。
      - [x] **P2（2/N）org + user 域 + 全枚举**：`org.py`（Organization /
      OrganizationMember）、`user.py`（User / UserSSOIdentity）；
      TaskStatus/TaskStage/AnnotationType/AnnotationSource/
      TaxonomyAnnotationMode/UserRole/Permission/OrganizationRole 与
      ROLE_PERMISSIONS 全部迁入 `enums.py`（User.has_permission 等方法的
      运行时依赖随之导入）；models.py 2917 → 2381 行。40 张表 DDL 仍逐字节
      一致，365 测试全绿，登录/用户/任务/数据集/效率真实 DB 冒烟 200，新文件
      E/F/I/N/W 零告警（继承的尾随空白顺手清理）。
      - [x] **P2（3/N）catalog 域**：`catalog.py` 承载 Taxonomy / Campaign /
      Dataset 与 `dataset_taxonomy_association` 关联表（多个 service/endpoint
      直接引用该 Table 对象，门面继续重导出）；models.py 2381 → 2017 行，
      Column/Table 两个仅关联表使用的死导入一并清除。40 张表 DDL 逐字节一致，
      365 测试全绿，datasets/campaigns/taxonomies/scenes 真实 DB 冒烟 200，
      新文件 E/F/I/N/W 零告警。
      **后续切片**：scene → task（含 history/audit）→ annotation → qa →
      chat/import；schema 归位随后进行。
- [ ] **P3 模块边界与工程化**：
  - `sam2_gpu_service.py` / `clip_gpu_service.py` 是独立部署的 FastAPI 进程，
    应移出 `app/services/`（建议顶层 `microservices/`），让 `services/` 只放领域服务；
  - 解开 `workflow_service` ↔ `dataops_service` 的懒加载循环依赖；
  - 生产环境收敛为只走 Alembic，停用启动期 `create_all`；
  - 清理 endpoint 中残留的 `print()` 调试输出，统一用 `logging`；
  - 推进 OpenAPI → TypeScript 类型生成，消除前端手写类型漂移。

### 重构一个新业务域的推荐步骤

1. 识别该域 endpoint 中重复出现的业务规则与跨文件 helper；
2. 在 `services/` 新建领域 service，把规则与数据访问平移进去，不抛 HTTP 异常；
3. endpoint 改为鉴权 + 调 service + HTTP 映射的薄骨架，URL / 响应模型保持不变；
4. 为 service 补纯单元测试；
5. 跑 `pytest -q` 与 `python -m compileall app`，必要时构建 OpenAPI 确认契约不变。
