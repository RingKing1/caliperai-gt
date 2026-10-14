# Sensor Fusion Annotation Platform

An open-source, production-grade annotation platform for autonomous-driving sensor
data. Label **LiDAR point clouds** and **camera images** together with real-time
3D-to-2D projection, multi-object tracking, and a full human review workflow.

📺 **[Feature walkthroughs & how-to videos](https://www.youtube.com/@CaliperAI-f7u)**

- **Backend:** FastAPI (Python 3.11), PostgreSQL + pgvector, Redis, MinIO
- **Frontend:** React 18 + TypeScript, Three.js, Zustand
- **AI-assist:** SAM2 segmentation (bring your own downloadable model)
- **Optional:** Ollama-powered in-app assistant/chatbot

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start (Docker)](#quick-start-docker)
5. [Configuration](#configuration)
6. [Verify It Works](#verify-it-works)
7. [Importing Your Data](#importing-your-data)
8. [AI-Assisted Segmentation (SAM2)](#ai-assisted-segmentation-sam2)
9. [Production Deployment](#production-deployment)
10. [Local Development (without Docker)](#local-development-without-docker)
11. [Feature Toggles & Branding](#feature-toggles--branding)
12. [Keyboard Shortcuts](#keyboard-shortcuts)
13. [Project Structure](#project-structure)
14. [Enterprise](#enterprise)
15. [Contributing](#contributing)
16. [License](#license)

---

## Features

**Annotation**
- **3D cuboids** — full-rotation bounding boxes (yaw / pitch / roll) on LiDAR
- **2D boxes, polylines, polygons, keypoints** on camera images
- **3D semantic segmentation** — per-point LiDAR labeling
- **AI-assisted segmentation (SAM2)** — click-to-segment in 2D images and a
  Segment-to-3D workflow; runs against a downloadable SAM2 model
- **Manual lane / polyline editing** — Bézier + smoothing helpers
- **View-aware & box-local arrow key nudging** — `←`/`→`/`↑`/`↓` fine-tuning
  aligned to the object's local heading yaw in Top/BEV view (`→` forward, `←` backward,
  `↑` left, `↓` right) and orthographic planes in Side/Front views

**Sensor fusion**
- Real-time 3D→2D projection via calibration matrices
- Multi-camera synchronized views; orthographic BEV / Side / Front editing

**Multi-object tracking**
- Track management across frames with keyframe interpolation
- Track merging and 4D temporal stacking
- **Keyframe-only sampling mode & interval stepping** — sample every N frames
  (e.g. every 10 frames) from a chosen start frame with automatic step jumping


**Workflow & review**
- Campaigns → Datasets → Scenes → Tasks lifecycle
- Human **QA review** workflow (Annotation → QA → Customer QA → Accepted) with
  manual issue flagging and false-negative marking
- **RBAC** (admin, project_manager, annotator, qa_reviewer, customer_qa) and
  optional **SSO/OIDC** (Google, Azure AD, Okta, Keycloak)

**Data**
- Import/export (KITTI-style and platform-native formats)
- Optional Google Cloud Storage sync
- Taxonomies with class + attribute configuration
- PM analytics dashboard
- Optional in-app AI assistant (RAG over a bundled knowledge base, via Ollama)

---

## Architecture

```
                         ┌──────────────┐
   Browser ── :3000 ───► │   frontend   │  React + nginx (serves SPA, proxies /api)
                         └──────┬───────┘
                                │ /api/v1
                         ┌──────▼───────┐
                         │   backend    │  FastAPI (:8000)
                         └──┬───┬───┬───┘
              ┌─────────────┘   │   └─────────────┐
        ┌─────▼─────┐    ┌──────▼─────┐    ┌──────▼──────┐
        │ postgres  │    │   redis    │    │    minio    │
        │ +pgvector │    │  (cache)   │    │  (objects)  │
        └───────────┘    └────────────┘    └─────────────┘

   Optional:  sam2 (AI segmentation)   ·   ollama (in-app assistant)
```

---

## Prerequisites

- **Docker** 24+ and **Docker Compose** v2
- ~4 GB free RAM for the core stack
- (Optional) an NVIDIA GPU + `nvidia-container-toolkit` for SAM2 GPU inference
- (Optional) Node 20+ and Python 3.11 for running services outside Docker

---

## Quick Start (Docker)

```bash
# 1. Clone
git clone https://github.com/caliperai-ai/caliperai-gt.git && cd caliperai-gt

# 2. Configure — copy the template and set at least SECRET_KEY (>= 32 chars)
cp .env.example .env
#   edit .env:  SECRET_KEY, POSTGRES_PASSWORD, MinIO credentials

# 3. Start the core stack (postgres, redis, minio, backend, frontend)
docker compose up -d postgres redis minio backend frontend

# 4. Create an admin user (tables auto-create on first backend start)
docker compose exec backend python scripts/create_admin.py \
  --email admin@example.com --username admin --password 'change-me-123'

# 5. Open the app
#    Frontend  -> http://localhost:3000
#    API docs  -> http://localhost:8000/docs   (dev only)
```

Log in with the credentials from step 4.

> **Locked out / forgot the password?** The admin script refuses to overwrite an
> existing user, so re-running it prints "already exists". To reset an existing
> user's password (and re-promote it to an active admin), add `--reset-password`:
>
> ```bash
> docker compose exec backend python scripts/create_admin.py \
>   --username admin --password 'new-password-123' --reset-password
> ```

> The `ollama` and any GPU services are optional and omitted above — the core
> stack runs without them. Add `ollama` to the `up` list to enable the in-app assistant.

---

## Configuration

Copy `.env.example` → `.env`. In Docker, service hostnames (postgres, redis, minio)
are wired automatically; you mainly set secrets and ports.

| Variable | Purpose | Notes |
|---|---|---|
| `SECRET_KEY` | JWT signing secret | **Required, ≥ 32 chars** |
| `POSTGRES_PASSWORD` | Postgres password | Set before first start |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | MinIO root credentials | Set `OBJECT_STORAGE_ACCESS_KEY`/`OBJECT_STORAGE_SECRET_KEY` to the same values (see `.env.example`) |
| `CORS_ORIGINS` | Allowed browser origins | e.g. `http://localhost:3000` |
| `*_PORT` | Host port mappings | Defaults: FE 3000, API 8000, PG 5432, Redis 6379, MinIO 9000/9001 |
| `BUILD_TARGET` | `development` or `production` | Dev = hot reload |
| `LLM_PROVIDER` / `OLLAMA_*` | In-app assistant | Optional |
| `SSO_*` | OIDC providers | Optional; leave blank to disable |

Feature-gating (`FEATURE_*`) and branding (`BRAND_*`) are described under
[Feature Toggles & Branding](#feature-toggles--branding).

---

## Verify It Works

```bash
# All core containers healthy?
docker compose ps

# Backend health
curl -s http://localhost:8000/health

# Log in via the API (default user: admin / admin123)
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'
```

Then open http://localhost:3000, sign in, create a Campaign → Dataset, upload a
scene, and open a task to annotate.

---

## Importing Your Data

Annotation work starts from an imported **scene** — a `.zip` bundling LiDAR
point clouds, camera images, and sensor calibration. The minimum viable bundle
is just a `lidar/` folder of point clouds:

```
my_scene/
├── lidar/            frame_000000.pcd, frame_000001.pcd, …   (.pcd or .bin)
├── cameras/          front/frame_000000.jpg, left/…          (optional)
├── calibration.json  LiDAR↔camera extrinsics + intrinsics    (optional)
└── ego_poses/poses.json   per-frame ego trajectory           (optional)
```

Create a Campaign → Dataset in the UI, then **Import** the zip into the dataset.

👉 **Docs:**
- [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md) — the scene bundle: point-cloud/image
  formats, `calibration.json` and ego-pose shapes, coordinate conventions, and the
  `/api/v1/import/upload-zip` endpoint.
- [`docs/ANNOTATION_FORMATS.md`](docs/ANNOTATION_FORMATS.md) — annotation
  **import/export** formats and JSON schemas (platform-native, KITTI, COCO,
  SemanticKITTI) and the export endpoints.
- [`docs/ANNOTATION_GUIDE.md`](docs/ANNOTATION_GUIDE.md) — how to **use** the
  annotation tools (3D cuboids, segmentation, 2D, tracking, QA).

> **Tip:** frames are matched by sorted filename position, so zero-pad names
> identically across `lidar/` and every `cameras/<cam>/` folder
> (`frame_000000`, `frame_000001`, …).

**Just have a video?** You can also upload a **video file** (MP4/AVI/MOV/MKV/WebM)
and the platform extracts its frames into a camera-only scene for 2D annotation —
no bundle needed (requires `ffmpeg` on the backend). See the *Video input* section
of [`docs/DATA_FORMAT.md`](docs/DATA_FORMAT.md#video-input-extract-frames-from-a-video).

### Try it with demo data

No data of your own yet? Grab a ready-made scene from our **public** demo bucket —
**no GCS account or credentials needed** (the objects are anonymously readable).
Each scene is a `.zip`; download it and import via **Dataset → Import**.

```bash
# 3D semantic segmentation
curl -L -O "https://storage.googleapis.com/customer-demo-datasets/caliper-gt-demo/3D/3D%20segmentation/Segmentation.zip"

# 3D + camera sensor fusion
curl -L -O "https://storage.googleapis.com/customer-demo-datasets/caliper-gt-demo/3D/Sensor%20fusion/Sensor_fusion.zip"

# 2D object detection
curl -L -O "https://storage.googleapis.com/customer-demo-datasets/caliper-gt-demo/2D/Object_detection.zip"

# …or browse every demo scene (public bucket, no auth):
gsutil ls "gs://customer-demo-datasets/caliper-gt-demo/**/*.zip"
```

Then create a Campaign → Dataset and **Import** the downloaded `.zip`.
(`%20` in the URLs just encodes the spaces in the folder names.)

---

## AI-Assisted Segmentation (SAM2)

SAM2 powers the interactive **AI Segment** (2D), **Segment-to-3D**, and cross-frame **Video Propagation** tools. You can run SAM2 locally with GPU acceleration (recommended) or on CPU:

```bash
# 1. Download SAM2 model weights (large, base, small, or tiny)
python backend/scripts/download_sam2_models.py --size large --output-dir ./models/sam2

# 2. Create compatibility symlink for model loader
cd models/sam2 && ln -sf sam2_hiera_large.pt sam2.1_hiera_large.pt && cd ../..

# 3. Configure .env
# Set SAM2_MODE=api and SAM2_API_URL=http://sam2:8001 (or keep SAM2_MODE=mock for dummy testing)

# 4. Start SAM2 service with GPU acceleration (requires NVIDIA GPU + Container Toolkit):
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d sam2 backend

# Or run CPU-only SAM2 service:
docker compose -f docker-compose.yml -f docker-compose.sam2.yml up -d sam2 backend
```

Once started, the backend automatically routes interactive prompts and video propagation requests to the SAM2 inference microservice (`:8001`). Check health via `curl http://localhost:8001/health`.

---

## Production Deployment

The stack is domain-agnostic — **you supply your own hostname and TLS**; nothing
is hardcoded. Configure everything through `.env`.

```bash
# 1. Create your production env and set YOUR values
cp .env.production.example .env
#    In .env, set at minimum:
#      SECRET_KEY, POSTGRES_PASSWORD, MinIO creds     — strong, unique secrets
#      DOMAIN=annotate.example.com                    — your public hostname
#      CORS_ORIGINS=https://annotate.example.com      — your public URL(s)

# 2. Start the stack
docker compose -f docker-compose.prod.yml up -d
#    + GPU/SAM2:
docker compose -f docker-compose.prod.yml -f docker-compose.prod.gpu.yml up -d

# 3. The backend auto-creates the schema on first start. On a FRESH database,
#    stamp that state so future migrations apply cleanly:
docker compose -f docker-compose.prod.yml exec backend alembic stamp head
#    (Upgrading an EXISTING deployment instead? Run: alembic upgrade head)

# 4. Create the first admin
docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py
```

**Using your own domain.** The frontend calls the API at a relative `/api` path,
so it works on any hostname; the backend's allowed origins come from
`CORS_ORIGINS`; and the bundled nginx accepts any host (`server_name _`). To go
live: point your DNS at the host, terminate TLS at your edge/reverse proxy (or
mount certs via `SSL_CERT_PATH`/`SSL_KEY_PATH`), and set `CORS_ORIGINS` to your
public URL. The bundled frontend nginx proxies `/api` to the backend — see
`frontend/nginx.proxy.conf`.

---

## Local Development (without Docker)

> **Optional.** Running the platform needs **Docker only** (see
> [Quick Start](#quick-start-docker)) — you never have to install Node or Python
> locally. This section is just for contributors who want to iterate on the
> frontend/backend outside containers (e.g. Vite hot-reload). The Docker image
> builds the frontend with `npm` internally.

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .            # or: pip install -r requirements
uvicorn app.main:app --reload --port 8000
```

**Frontend**
> For detailed architecture, modular component design, and data flows, see [frontend/README.md](frontend/README.md).

**Backend**
> For the FastAPI layering conventions, services, data model, deployment, and the refactor roadmap, see [backend/README.md](backend/README.md).

```bash
cd frontend
npm install
npm run dev                 # Vite dev server on :5173
npm run build               # type-check + production bundle
```

You still need Postgres, Redis, and MinIO running (the quick-start compose can
provide just those: `docker compose up -d postgres redis minio`).

---

## Feature Toggles & Branding

Optional UI features can be hidden per deployment without a rebuild:

- Flags live in a committed file, e.g. `deploy/features/caliper.env`
  (`FEATURE_PM_DASHBOARD=`, `FEATURE_CHAT=`; blank = on, `off` = hidden).
- The frontend loads them via `env_file:` → `docker-entrypoint.d/20-features.sh`
  regenerates `window.__FEATURES__` on container start.
- Register a new flag in `frontend/src/config/features.ts`, wrap its UI in
  `<FeatureGate feature="...">`, then add a `FEATURE_*` line.

Branding works the same way via `BRAND_*` env → `10-brand.sh` → `window.__BRAND__`
(`frontend/src/config/branding.ts`), so a single image can be re-skinned at runtime.

---

## Keyboard Shortcuts

### General & 3D Cuboid Editing

| Key | Action | | Key | Action |
|---|---|---|---|---|
| `V` | Select tool | | `Q` / `E` | Rotate yaw ±5° (cuboid) |
| `C` | 3D Cuboid tool | | `Shift+Q` / `Shift+E` | Rotate yaw ±1° |
| `B` | 2D Bounding Box | | `R` | Reset rotation |
| `L` | Polyline / Lane tool | | `W` / `S` | Resize length (±0.1 m) |
| `P` | Polygon (manual) | | `A` / `D` | Resize width (±0.1 m) |
| `W` | AI Segment (SAM2) | | `Z` / `X` | Resize height (±0.1 m) |
| `T` | Track tool | | `Delete` / `Backspace` | Delete selected |
| `Ctrl+S` / `Cmd+S` | Save annotations | | `Space` | Play / Pause playback |

### Directional Arrow Keys (`←` / `→` / `↑` / `↓`)

- **When a 3D cuboid is selected (Fine Nudging, ±0.05 m; `Shift` for ±0.01 m):**
  - **Top (BEV) View**: Coordinate system is locked to the cuboid's local heading yaw:
    - `→`: Move forward along heading direction (+X local, towards screen right)
    - `←`: Move backward along heading direction (-X local)
    - `↑`: Move lateral left (+Y local)
    - `↓`: Move lateral right (-Y local)
  - **Side View**: `←` / `→` along horizontal axis, `↑` / `↓` along vertical Z (height).
  - **Front View**: `←` / `→` along horizontal axis, `↑` / `↓` along vertical Z (height).
- **When no cuboid is selected (Timeline Navigation):**
  - `←` / `→`: Navigate to previous / next frame (automatically respects keyframe interval step when keyframe sampling is enabled).

### Keyframe Sampling & Stepping

- Enable **Keyframes Only** mode on the timeline to restrict labeling to sampled frames.
- Configure **Keyframe Interval / Step** (e.g., sample every 10 frames) and **Start Frame** offset.
- Navigation buttons (`Prev` / `Next`) and arrow keys automatically step across keyframes according to the interval.

### QA Review

`1` approve · `2` reject · `3` flag · `F` flag missing object.

---

## Project Structure

```
caliperai-gt/
├── backend/
│   ├── app/
│   │   ├── api/v1/endpoints/   # REST API
│   │   ├── models/ schemas/    # SQLAlchemy models · Pydantic schemas
│   │   └── services/           # Business logic (QA workflow, SAM2, GCS, ...)
│   ├── alembic/                # DB migrations
│   ├── knowledge_base/         # RAG content for the in-app assistant
│   └── scripts/                # create_admin.py, download_sam2_models.py, ...
├── frontend/
│   └── src/
│       ├── components/canvas/  # LidarCanvas, OrthographicViews, 2D view
│       ├── pages/              # FusionEditorV2, dashboards, taxonomy, ...
│       ├── config/             # branding.ts, features.ts
│       └── store/              # Zustand stores
├── deploy/features/            # committed feature-toggle profiles
├── docker-compose.yml          # dev stack
├── docker-compose.prod.yml     # production stack
└── docker-compose.sam2.yml / .gpu.yml  # optional SAM2 / GPU overrides
```

---

## Enterprise

The open-source platform is fully featured and self-hostable. **CaliperGT
Enterprise** layers on an **AI auto-annotation engine** and an **enterprise-grade
security & compliance** stack — so your team hand-labels a fraction of the frames,
ships ground truth in a fraction of the time, and stays audit-ready.

### ⭐ Flagship

- **VLA (Vision-Language-Action) ground truth** — the tooling to build training
  data for **vision-language-action and end-to-end driving/robotics foundation
  models**: natural-language scene descriptions, instruction & reasoning traces,
  and **action grounding** aligned to synchronized LiDAR + camera. Produce the
  datasets the next generation of autonomous systems is trained on — not just
  boxes and masks.
- **3D LiDAR auto-annotation** — automatic **3D cuboids and per-point segmentation**
  straight from raw point clouds, with **cross-frame tracking and stable track
  IDs**. Turn weeks of manual 3D labeling into a fast review-and-correct pass.

### 🤖 AI auto-annotation — stop labeling from scratch

Beyond the flagship 3D LiDAR engine above:

- **Highly optimized 2D auto-annotation** — detection, segmentation, and keypoints
  powered by **foundation models fine-tuned on your domain** (driving, retail,
  agriculture, industrial…). Far higher accuracy than off-the-shelf models, so the
  pre-labels are production-usable, not throwaway.
- **AI lane detection** — automatic lane, curb, and road-marking extraction as
  clean, Bézier-smoothed polylines — turning hours of manual lane tracing into a
  quick QA pass.
- **Active-learning loop** — models continuously retrain on your accepted labels
  and keep getting sharper on *your* data.

### 🔒 Security & compliance

- **Encryption everywhere** — field-level **PII encryption at rest**, **encrypted
  object storage (SSE)**, and **mutual TLS** between every internal service.
- **Compliance-ready** — full **audit logging**, data-retention controls, and
  support for your **SOC 2 / GDPR / ISO 27001** programs.
- **Governance & isolation** — advanced role controls, **per-project/tenant data
  isolation**, and **air-gapped / in-VPC deployment** — nothing leaves your
  infrastructure. (The open-source edition already includes SSO/OIDC + RBAC.)

### ⚙️ Operations & scale

- **Managed hosting & auto-scaling** — deployment, upgrades, and ops handled for you.
- **Team operations & analytics** — live throughput, quality, and efficiency
  dashboards across a distributed annotation workforce.
- **Self-hosted LLM assistant** — a private, in-app copilot running entirely on
  your own infrastructure.
- **Priority support & SLAs**, guided onboarding, and custom integrations / model
  fine-tuning on your data.

📧 **See the difference on your own data** — contact
**[info@caliperai.ai](mailto:info@caliperai.ai)** for a demo.

---

## Contributing

Contributions are welcome — bug reports, docs, tests, and code. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and pull-request
workflow, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community guidelines.

Found a security issue? Please report it privately — see
[SECURITY.md](SECURITY.md). Do not open a public issue for vulnerabilities.

---

## License

Licensed under the [Apache License 2.0](LICENSE) © Caliper AI. See
[NOTICE](NOTICE) for attribution.
