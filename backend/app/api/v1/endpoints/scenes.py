"""
Scene endpoints with RBAC protection.

Business logic lives in ``app.services.scene_service`` (CRUD, filter parsing,
on-disk frame image lookup); this module only handles auth dependencies,
HTTP status mapping and image thumbnail/streaming responses.

``_resolve_frame_image_path`` is re-exported for the legacy test import path.
"""
import logging
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Permission, Scene, User
from app.schemas.schemas import (
    SceneCreate,
    SceneResponse,
    SceneSearchResponse,
    SceneUpdate,
)
from app.services import scene_service
from app.services.dataset_service import DatasetNotFoundError
from app.services.rbac_service import (
    RequirePermissions,
    RequirePermissionsWithQuery,
)
from app.services.scene_service import (
    FrameImageNotFoundError,
    FrameNotFoundError,
    SceneConflictError,
    SceneNotFoundError,
    SceneValidationError,
    resolve_frame_image_path,
)

# Legacy name re-exported for existing imports/tests.
_resolve_frame_image_path = resolve_frame_image_path

router = APIRouter()

logger = logging.getLogger(__name__)

__all__ = ["_resolve_frame_image_path"]


def _http_for_scene_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            SceneNotFoundError,
            FrameNotFoundError,
            FrameImageNotFoundError,
            DatasetNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, SceneConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, SceneValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail
        )
    raise exc


@router.get("/search", response_model=SceneSearchResponse)
async def search_scenes_by_labels(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    q: str | None = Query(
        None,
        description="Class or class group, e.g. car, motorcycle, bicycle, two_wheeler, vehicle, pedestrian",
    ),
    classes: list[str] = Query(default_factory=list, description="Required classes; repeat or comma-separate"),
    groups: list[str] = Query(default_factory=list, description="Required class groups; repeat or comma-separate"),
    dataset_id: UUID | None = Query(None),
    name_contains: str | None = Query(None),
    min_objects: int = Query(0, ge=0),
    min_class_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_frame_ratio: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Search scenes by imported label statistics (class presence/count/ratio)."""
    try:
        return await scene_service.search_by_labels(
            db,
            q=q,
            classes=classes,
            groups=groups,
            dataset_id=dataset_id,
            name_contains=name_contains,
            min_objects=min_objects,
            min_class_ratio=min_class_ratio,
            min_group_ratio=min_group_ratio,
            min_group_frame_ratio=min_group_frame_ratio,
            page=page,
            page_size=page_size,
        )
    except SceneValidationError as exc:
        raise _http_for_scene_error(exc)


@router.get("/search/hybrid")
async def search_scenes_hybrid_endpoint(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    # semantic layer (optional; omit for structured-only mode)
    semantic_q: str | None = Query(
        None,
        description="Free-text visual semantics, e.g. 堵车, 雨夜路口, 施工路段",
    ),
    cameras: list[str] = Query(default_factory=list, description="CLIP cameras; repeat or comma-separate"),
    min_similarity: float = Query(0.0, ge=-1.0, le=1.0),
    top_k_frames: int = Query(200, ge=1, le=2000),
    candidate_pool: int | None = Query(None, ge=100, le=100000),
    preview_frames: int = Query(5, ge=0, le=20),
    # structured layer
    q: str | None = Query(None, description="Class/group, e.g. car, two_wheeler, 二轮车"),
    classes: list[str] = Query(default_factory=list),
    groups: list[str] = Query(default_factory=list),
    dataset_id: UUID | None = Query(None),
    name_contains: str | None = Query(None),
    min_objects: int = Query(0, ge=0),
    min_class_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_ratio: float = Query(0.0, ge=0.0, le=1.0),
    min_group_frame_ratio: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Hybrid search: exact label filters first, then CLIP semantic ranking.

    With ``semantic_q`` omitted this returns structured-only matches.
    """
    try:
        return await scene_service.search_hybrid(
            db,
            semantic_q=semantic_q,
            cameras=cameras,
            min_similarity=min_similarity,
            top_k_frames=top_k_frames,
            candidate_pool=candidate_pool,
            preview_frames=preview_frames,
            q=q,
            classes=classes,
            groups=groups,
            dataset_id=dataset_id,
            name_contains=name_contains,
            min_objects=min_objects,
            min_class_ratio=min_class_ratio,
            min_group_ratio=min_group_ratio,
            min_group_frame_ratio=min_group_frame_ratio,
            page=page,
            page_size=page_size,
        )
    except SceneValidationError as exc:
        raise _http_for_scene_error(exc)


@router.get("/search/semantic")
async def search_scenes_by_image_semantics(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    q: str = Query(..., min_length=1, description="Natural-language scene query, e.g. 二轮车场景, cars on highway"),
    dataset_id: UUID | None = Query(None),
    cameras: list[str] = Query(default_factory=list, description="Filter cameras; repeat or comma-separate"),
    min_similarity: float = Query(0.18, ge=-1.0, le=1.0),
    top_k_frames: int = Query(200, ge=1, le=2000),
    candidate_pool: int | None = Query(None, ge=100, le=100000, description="Limit ANN candidates; default scans all frames for accurate scene ranking"),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Semantic scene search over CLIP frame embeddings (Chinese-CLIP)."""
    return await scene_service.search_semantic(
        db,
        query_text=q,
        dataset_id=dataset_id,
        cameras=cameras,
        min_similarity=min_similarity,
        top_k_frames=top_k_frames,
        candidate_pool=candidate_pool,
        page_size=page_size,
    )


@router.get("/embeddings/coverage")
async def get_embedding_coverage(
    current_user: Annotated[
        User,
        Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-scene CLIP frame-embedding coverage."""
    return await scene_service.get_embedding_coverage(db)


@router.get("/{scene_id}/frames/{frame_index}/image")
async def get_frame_camera_image(
    scene_id: UUID,
    frame_index: int,
    current_user: Annotated[
        User,
        Depends(RequirePermissionsWithQuery(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False)),
    ],
    camera: str = Query("front"),
    width: int = Query(400, gt=0, le=4096, description="Thumbnail width; keeps aspect ratio"),
    quality: int = Query(80, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Camera image (thumbnail-resized) for a frame, addressable by scene+frame+camera."""
    try:
        image_path = await scene_service.get_frame_camera_image_path(
            db, scene_id, frame_index, camera
        )
    except (FrameNotFoundError, FrameImageNotFoundError) as exc:
        raise _http_for_scene_error(exc)

    ext = image_path.suffix.lower()
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        ext, "application/octet-stream"
    )
    try:
        from PIL import Image

        img = Image.open(image_path)
        if img.mode == "RGBA" and ext in (".jpg", ".jpeg"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        orig_w, _ = img.size
        if width and orig_w > width:
            ratio = width / orig_w
            img = img.resize((width, max(1, int(img.size[1] * ratio))), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        if ext in (".jpg", ".jpeg"):
            img.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
            media_type = "image/jpeg"
        elif ext == ".png":
            img.save(buffer, format="PNG", optimize=True)
        elif ext == ".webp":
            img.save(buffer, format="WEBP", quality=quality)
        else:
            return FileResponse(image_path, media_type=media_type)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("frame image resize failed, returning original: %s", exc)
        return FileResponse(image_path, media_type=media_type)


@router.post("", response_model=SceneResponse, status_code=status.HTTP_201_CREATED)
async def create_scene(
    scene_in: SceneCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Create a new scene with calibration matrices. Requires SCENES_CREATE permission."""
    try:
        return await scene_service.create_scene(db, scene_in)
    except (DatasetNotFoundError, SceneConflictError) as exc:
        raise _http_for_scene_error(exc)


@router.get("", response_model=list[SceneResponse])
async def list_scenes(
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ, Permission.SCENES_READ_ALL, require_all=False))],
    dataset_id: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Scene]:
    """List scenes with optional dataset filter. Requires SCENES_READ permission."""
    return await scene_service.list_scenes(db, dataset_id, page, page_size)


@router.get("/{scene_id}", response_model=SceneResponse)
async def get_scene(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Get a scene by ID. Requires SCENES_READ permission."""
    try:
        return await scene_service.get_scene(db, scene_id)
    except SceneNotFoundError as exc:
        raise _http_for_scene_error(exc)


@router.get("/{scene_id}/calibration")
async def get_calibration(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_READ))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get calibration matrices for a scene. Requires SCENES_READ permission."""
    try:
        return await scene_service.get_calibration(db, scene_id)
    except SceneNotFoundError as exc:
        raise _http_for_scene_error(exc)


@router.patch("/{scene_id}", response_model=SceneResponse)
async def update_scene(
    scene_id: UUID,
    scene_in: SceneUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> Scene:
    """Update a scene. Requires SCENES_UPDATE permission."""
    try:
        return await scene_service.update_scene(db, scene_id, scene_in)
    except SceneNotFoundError as exc:
        raise _http_for_scene_error(exc)


@router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scene(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.SCENES_DELETE))],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a scene. Requires SCENES_DELETE permission (Admin only)."""
    try:
        await scene_service.soft_delete_scene(db, scene_id)
    except SceneNotFoundError as exc:
        raise _http_for_scene_error(exc)
