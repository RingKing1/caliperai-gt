# 标注工作台刷新数据量分析与显示优化方案

> 适用范围：融合标注编辑器（`FusionEditorV2`）打开/刷新场景、切帧播放时的点云与多路相机图像加载。
> 数据来源：测试数据包 `test_6cam_10frames.zip`（6 相机 × 10 帧）实测 + 前后端代码走查 + 接口实测。

## 1. 单帧数据量实测

测试数据：LiDAR 230,400 点/帧（`x y z intensity` 各 float32），6 路 1920×1080 JPEG。

| 数据类型 | 现状（传输形态） | 单帧大小 | 说明 |
|---|---|---|---|
| 点云 | `/data/lidar?format=binary`，16 字节/点，gzip 传输 | 原始 3.52 MB → **实际 1.64 MB** | gzip 压缩率 2.24x，Redis 缓存压缩产物 |
| 6 路原图 | `/data/image/` 直出 1920px JPEG | **4.41 MB**（6 张合计，单张 0.6–0.9 MB） | 无任何缩放 |
| 6 路 400px 缩略图 | 后端实时缩放，JPEG q80 | **0.145 MB** | 约为原图 1/30，单张 13–30 KB |
| 6 路 800px 缩略图 | 同上 | **0.52 MB** | 约 1/8.5 |
| 6 路 1280px 缩略图 | 同上 | **1.14 MB** | 约 1/3.9 |

后端实时缩放（PIL LANCZOS + JPEG 编码）单次约 **10 ms**，CPU 开销可忽略。

## 2. 刷新一次页面实际拉多少（优化前）

前端加载策略（代码位置：`frontend/src/hooks/useTaskDataLoader.ts`、`src/store/`）：

- **点云**：打开场景预取当前帧 ±10 共 21 帧。21 × 1.64 MB（gzip 后）≈ **34 MB 传输量**（未压缩内存 74 MB）；切帧时以 ±10 窗口继续补取。
- **图像**：`imageCacheStore.startPrefetch` 对**整个场景的所有帧 × 全部相机**预取**原图**，并发 30。
  - 10 帧测试场景：60 张 ≈ **44 MB**
  - 真实场景（库内平均 2538 帧、最大 2993 帧）：理论峰值 **8–13 GB**；受 1 GB 内存缓存上限影响，会边下边淘汰，变成持续的后台流量
- **每次刷新全部重下**：图像预取使用 `cache: 'no-store'`，内存 blob 缓存随页面刷新清空，浏览器磁盘缓存与 CDN 边缘缓存均被绕过。

**瓶颈排序**：

1. 图像全场景原图预取（长场景下占总流量 95% 以上）
2. 点云预取窗口过大（±10）
3. 无浏览器/CDN 缓存兜底，二次刷新零复用

经 Cloudflare Tunnel 公网访问时，以上流量全部经过隧道，弱网下卡顿明显。

## 3. P0 优化（本期实施）

目标：把"打开场景"的传输量从 GB 级（长场景）压到几十 MB 级，二次刷新接近零传输，且不损失标注精度。

### P0-1 图像分级 + 有界窗口预取

`imageCacheStore` 由"全场景原图"改为以当前帧为中心的两档窗口：

| 档位 | 窗口（单侧） | 分辨率 | 单场景最大传输量 |
|---|---|---|---|
| near（原图） | ±3 帧（7 帧 × 6 路 = 42 张） | 1920px 原图 | ≈ 31 MB |
| far（缩略图） | ±15 帧（31 帧 × 6 路 = 186 张） | 400px q80 | ≈ 4.4 MB |
| 窗口之外 | 不预取 | — | 切到再按窗口增量补取 |

切帧时按窗口增量补齐新进入的帧（`followWindow`），已缓存的不重复下载。

**精度保护（关键约束）**：

- 当前帧主标注视图（2D 像素标注、SAM2、相机投影大图）**只使用原图**。缓存查询默认 `allowThumb=false`，现有组件行为不变。
- 缩略图只供给纯 3D 投影展示组件（6 相机小卡 `FocusedCameraViews`），用于快速切帧时即时出图。
- 小卡上的 3D 框投影**锚定相机标定的原始分辨率**（`intrinsic.resolution`，缺失时回退 `cx*2`），而不是图片的 `naturalWidth`。缩略图是等比缩放的，投影坐标空间固定在标定分辨率后，喂任意宽度的图投影都不会错位（修复了历史上 600px 缩略图投影错位的问题）。
- 原图到达后自动替换缩略图，肉眼表现为先清晰后无损。

### P0-2 打开浏览器/CDN 缓存

- 预取请求改用 `Authorization` 请求头传 JWT（后端 `RequirePermissionsWithQuery` 同时支持 header 与 query token），URL 不再带 token，缓存键稳定；浏览器 HTTP 缓存可跨刷新复用。
- 预取 fetch 由 `cache: 'no-store'` 改为默认缓存模式。
- 后端响应头：
  - 原图：`Cache-Control: private, max-age=604800, immutable`（传感器数据不可变；带用户态故 private）
  - 缩略图：`max-age` 由 3600 提升到 604800（URL 含 `width` 参数，天然按分辨率区分）
- 效果：二次刷新从浏览器磁盘缓存读取（200 from disk / 304），Cloudflare 边缘也可缓存缩略图。

### P0-3 点云预取窗口 ±10 → ±3

初始窗口与切帧跟随窗口统一为 ±3（7 帧）。传输量 34 MB → 约 **11 MB**。快速播放时仍由窗口增量逻辑在后台补帧。

### P0-4 点云 gzip 压缩（已具备，验证生效）

后端 `/data/lidar` 早已实现：请求带 `Accept-Encoding: gzip` 时返回 gzip 流（gzip level 1，压缩产物入 Redis 缓存）。浏览器 fetch 自动带该头并透明解压，前端 `arrayBuffer()` 解析逻辑无需改动。

实测：230,400 点帧 `3,686,408 → 1,644,003 字节（2.24x）`，响应头含 `content-encoding: gzip`。本期仅做验证与记录，无代码改动。

### 优化效果汇总

| 场景 | 优化前 | P0 后（首次打开） | 二次刷新 |
|---|---|---|---|
| 10 帧测试场景 | ≈ 79 MB | ≈ 46 MB（图像 35 + 点云 11） | ≈ 0（磁盘缓存） |
| 2500+ 帧真实场景 | 34 MB 点云 + GB 级图像后台流 | ≈ 46 MB 收敛，与场景长度无关 | ≈ 0 |

> 注：near 窗口原图 31 MB 是当前帧 ±3 的保守取值；后续 P1 可进一步把邻帧降为 1280px。

## 4. P1 优化（已实施）

### P1-1 缩略图磁盘缓存

新增 `backend/app/services/thumbnail_cache.py`：缩略图按「源文件 mtime/size + 尺寸 + 质量」哈希分片落盘（`THUMB_CACHE_DIR`，compose 中指向持久卷 `/uploads/.thumb-cache`），临时文件 rename 防并发竞争，源文件替换自动失效，不放大。`/data/image` 与 `/scenes/{id}/frames/{n}/image` 两个缩放端点统一复用，命中后走 sendfile。

实测：同档缩略图重复请求 88 ms → **3 ms**（约 30 倍）。

### P1-2 点云 LOD 分级（full / coarse）

- 后端 `/data/lidar` 新增 `lod=full|coarse`：coarse 为固定种子随机抽稀到约 1/4（2 万～10 万点），确定性结果，gzip 压缩产物复用 Redis 缓存（缓存键含点数天然区分），ETag/X-Subsampled 头自动反映。
- `lidarCacheStore` 缓存按 path 单层存放、tier 标记，full 到达替换 coarse 并 bump `fullUpgradeTick`；窗口中心帧 full、邻帧 coarse；`ensureFull` 支持占位升级。
- 当前帧 react-query 接受 coarse 即时显示，监听 tick 自动 invalidate 升级为 full；逐点分割编辑器仍只取 full。

实测（230,400 点帧，gzip 传输）：full 1.64 MB / 230,400 点，coarse **0.62 MB / 57,600 点**。7 帧窗口点云传输 11.5 MB → **5.4 MB**。

### P1-3 图像三档窗口

图像预取由两档升级为三档：±1 full（保证逐帧播放零等待）、±2～±3 mid(1280)、±4～±15 thumb(400)；tier 按 rank(full>mid>thumb) 去重、防降级、防并发。`getCached(path, minTier)` 按档查询：

- 纯 3D 投影小卡（FocusedCameraCard）允许 thumb/mid 即时显示，投影锚定标定分辨率（P0 已建立）；
- FusionLabelingView 大图叠的是**可交互 2D bbox**（viewBox 为图片自然像素空间），坐标必须像素精确，因此坚持 full，不做缩略图占位；
- 2D 标注、SAM2 链路同样 full-only。

### P1 后首次打开传输量（7 帧工作窗口，与场景长度无关）

| 组成 | 档位/帧数 | 流量 |
|---|---|---|
| 图像 full | ±1，3 帧 × 6 路原图 | 13.2 MB |
| 图像 mid 1280 | ±2～±3，4 帧 × 6 路 | 4.6 MB |
| 图像 thumb 400 | ±4～±15，24 帧 × 6 路 | 3.5 MB |
| 点云 full | 1 帧 | 1.6 MB |
| 点云 coarse | 6 帧 × 0.62 MB | 3.7 MB |
| **合计** | | **≈ 26.6 MB**（P0 约 46 MB） |

二次刷新仍由浏览器磁盘缓存/ETag 兜底，接近零传输。

## 5. P2 优化（已实施两项）

### P2-1 标注元数据窗口化（打开场景最大的单一请求）

实测最大任务（2993 帧 / 65,194 条 cuboid）：打开时 `GET /annotations-3d` 全量返回 **raw 44.5 MB / gzip 4.44 MB**，另有 `summary` 门闩请求 **gzip 1.64 MB**（该数据前端无消费者，仅用于串行等待）。

走查确认所有 UI（CuboidAnnotations、对象面板、LabelList 等）都按当前帧过滤渲染，全量 map 只用于轨迹引导（`initializeTracksFromAnnotations`，增量 merge 式），因此安全窗口化：

- 后端 `/annotations-3d` 新增 `frame_start`/`frame_end`（join frames 按 frame_index 过滤）；
- 编辑器全量拉取改为当前帧 ±50 的窗口，随播放头滚动增量 merge，本地脏标注受 `dirtyAnnotations` 保护不被覆盖；
- 删除无消费者的 summary 门闩请求；
- QA 面板（FrameAnnotationsTab/TrackReviewTab）本就只在质检模式条件挂载，保留全量（跨帧质检统计需要）；`TrackQAPanel` 为无引用死组件。

实测：gzip **4.44 MB → 0.08～0.11 MB/窗口**（约 98%），且消除 44.5 MB JSON 的主线程解析与 6.5 万对象驻留。

### P2-2 播放方向自适应预取

连续两步同向移动判定为播放（单步手动跳转/反向立即恢复对称窗口）：

- 图像 full(±1)/mid(±3) 近窗始终对称，保证双向跟手；
- thumb 远窗只向播放方向延伸到 ±15，后沿收在 ±3——播放中远窗帧数 24 → 12，thumb 流量约 **3.5 MB → 1.75 MB**；
- 点云 coarse 窗（±3）保持对称（总量仅 3.7 MB，回退也要跟手）。

### P2 后流量基线

| 场景 | 首次打开（静止/手动） | 连续播放每跨窗增量 |
|---|---|---|
| 传感器（P1 窗口） | 26.6 MB | — |
| 3D 标注元数据 | 0.1 MB（原 6.1 MB） | 0.1 MB |
| 播放时 thumb 远窗 | 3.5 MB → **1.75 MB** | 约 1.75 MB |

### 仍备选（未实施）

- WebP/AVIF 缩略图：实测 WebP 省 11%（400px）～20%（1280px），按 `Accept` 协商。
- Service Worker 缓存：多标签页共享/弱网离线可用，但需防标注数据陈旧。
- 点云 Draco / 帧间差分压缩：5–10x，前端需引入 WASM 解码器；coarse 已 0.62 MB/帧，优先级低。
- 缩略图边缘缓存：带 Authorization 头时 Cloudflare 不缓存；需 query-token 端点 + Cache Rule。

## 6. 涉及文件

| 文件 | 改动 |
|---|---|
| `frontend/src/store/imageCacheStore.ts` | 三档窗口预取（full ±1 / mid ±3 / thumb ±15）、rank 去重防降级、`followWindow`、header 鉴权、磁盘缓存 |
| `frontend/src/store/lidarCacheStore.ts` | full/coarse 双 tier，窗口中心 full、邻帧 coarse，`ensureFull` 占位升级，`fullUpgradeTick` 通知 |
| `frontend/src/hooks/useTaskDataLoader.ts` | 点云窗口 ±3；coarse 即时显示 + tick 触发 full 升级；图像窗口跟随与播放方向偏置；3D 标注 ±50 窗口增量 merge |
| `frontend/src/api/client.ts` | `getLidarData(path, { lod })`，响应携带 lod 标记；`annotation3DApi.list` 支持 frameStart/frameEnd |
| `frontend/src/components/editor/FocusedCameraViews.tsx` | 小卡允许 thumb/mid 占位；投影锚定标定分辨率 |
| `backend/app/api/v1/endpoints/data.py` | 图像缓存头；点云 `lod` 参数与确定性 coarse 抽稀 |
| `backend/app/api/v1/endpoints/annotations_3d.py` | 列表端点新增 `frame_start`/`frame_end` 帧范围过滤 |
| `backend/app/api/v1/endpoints/scenes.py` | frame image 端点复用缩略图缓存 |
| `backend/app/services/thumbnail_cache.py` | 缩略图磁盘缓存（新增） |
| `docker-compose.yml` | backend 增加 `THUMB_CACHE_DIR=/uploads/.thumb-cache` |

## 7. 验证方法

1. 打开 DevTools → Network，进入一个多帧场景：
   - `/data/image/` 请求仅覆盖当前帧 ±15：±2～±3 带 `width=1280`，±4～±15 带 `width=400`，±1 无 width；
   - `/data/lidar/` 请求仅覆盖 ±3：中心帧无 lod，邻帧带 `lod=coarse`，均含 `content-encoding: gzip`；
   - 邻帧点云响应头 `x-point-count` 约为全帧 1/4、`x-subsampled: 1`；
   - 二次刷新图像/缩略图为 `200 (disk cache)` 或 `304`；重复请求同一缩略图后端耗时约 3 ms。
2. 快速拖动时间轴：6 相机小卡先出 400/1280 预览（投影框不错位）；当前帧点云先密后疏地"补点"升级为全量。
3. 2D 标注模式画框、SAM2 分割、FusionLabelingView 大图 bbox：确认始终使用原图，坐标与标定像素空间一致。
4. 语义分割编辑器确认仍只取 full 点云（逐点分割不用 coarse）。
5. 缓存目录：`docker exec anno-backend find /uploads/.thumb-cache -type f | wc -l`。
