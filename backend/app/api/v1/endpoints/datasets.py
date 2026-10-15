"""
Dataset endpoints with RBAC protection.

Business logic lives in ``app.services.dataset_service``; this module only
handles authentication/authorization dependencies and HTTP status mapping.

``auto_create_tasks_for_scene`` is re-exported for the legacy import paths
used by the scene import pipeline.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Dataset, Permission, Taxonomy, User
from app.schemas.schemas import (
    DatasetCreate,
    DatasetDetailResponse,
    DatasetResponse,
    DatasetUpdate,
    TaxonomyResponse,
)
from app.services import dataset_service
from app.services.dataset_service import (
    CampaignNotFoundError,
    DatasetConflictError,
    DatasetNotFoundError,
    DatasetValidationError,
    TaxonomyNotFoundError,
    auto_create_tasks_for_scene,
)
from app.services.rbac_service import (
    RequirePermissions,
)

router = APIRouter()

__all__ = ["auto_create_tasks_for_scene"]


def _http_for_dataset_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc, (DatasetNotFoundError, CampaignNotFoundError, TaxonomyNotFoundError)
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, DatasetConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, DatasetValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    dataset_in: DatasetCreate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> Dataset:
    """Create a new dataset with taxonomy configuration. Requires DATASETS_CREATE permission."""
    try:
        return await dataset_service.create_dataset(db, dataset_in)
    except (CampaignNotFoundError, DatasetConflictError) as exc:
        raise _http_for_dataset_error(exc)


@router.get("", response_model=list[DatasetResponse])
async def list_datasets(
    current_user: Annotated[
        User,
        Depends(
            RequirePermissions(
                Permission.DATASETS_READ,
                Permission.DATASETS_READ_ALL,
                require_all=False,
            )
        ),
    ],
    campaign_id: Optional[UUID] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Dataset]:
    """List datasets with optional campaign filter. Requires DATASETS_READ permission."""
    return await dataset_service.list_datasets(db, campaign_id, page, page_size)


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    db: AsyncSession = Depends(get_db),
) -> Dataset:
    """Get a dataset by ID. Requires DATASETS_READ permission."""
    try:
        return await dataset_service.get_dataset(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.get("/{dataset_id}/detail", response_model=DatasetDetailResponse)
async def get_dataset_detail(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get dataset with related scenes/taxonomies/stats in one call. Requires DATASETS_READ."""
    try:
        return await dataset_service.get_dataset_detail(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(
    dataset_id: UUID,
    dataset_in: DatasetUpdate,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> Dataset:
    """Update a dataset. Requires DATASETS_UPDATE permission."""
    try:
        return await dataset_service.update_dataset(db, dataset_id, dataset_in)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_DELETE))],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a dataset. Requires DATASETS_DELETE permission (Admin only)."""
    try:
        await dataset_service.soft_delete_dataset(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.get("/{dataset_id}/taxonomy")
async def get_taxonomy(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the taxonomy configuration for a dataset. Requires DATASETS_READ permission."""
    try:
        return await dataset_service.get_embedded_taxonomy(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.get("/{dataset_id}/taxonomies", response_model=list[TaxonomyResponse])
async def get_dataset_taxonomies(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_READ))],
    db: AsyncSession = Depends(get_db),
) -> list[Taxonomy]:
    """Get all taxonomies associated with a dataset. Requires DATASETS_READ permission."""
    try:
        return await dataset_service.list_taxonomies(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.post("/{dataset_id}/taxonomies/{taxonomy_id}", status_code=status.HTTP_201_CREATED)
async def link_taxonomy_to_dataset(
    dataset_id: UUID,
    taxonomy_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Associate a taxonomy with a dataset. Requires DATASETS_UPDATE permission."""
    try:
        return await dataset_service.link_taxonomy(db, dataset_id, taxonomy_id)
    except (DatasetNotFoundError, TaxonomyNotFoundError, DatasetValidationError) as exc:
        raise _http_for_dataset_error(exc)


@router.post("/{dataset_id}/taxonomies/{taxonomy_id}/create-tasks", status_code=status.HTTP_200_OK)
async def create_tasks_for_taxonomy(
    dataset_id: UUID,
    taxonomy_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.TASKS_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create tasks for all scenes that don't already have one for this taxonomy."""
    try:
        return await dataset_service.create_tasks_for_taxonomy(
            db, dataset_id, taxonomy_id
        )
    except (DatasetNotFoundError, TaxonomyNotFoundError) as exc:
        raise _http_for_dataset_error(exc)


@router.delete("/{dataset_id}/taxonomies/{taxonomy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_taxonomy_from_dataset(
    dataset_id: UUID,
    taxonomy_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a taxonomy association from a dataset. Requires DATASETS_UPDATE permission."""
    try:
        await dataset_service.unlink_taxonomy(db, dataset_id, taxonomy_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.delete("/{dataset_id}/default-taxonomy", status_code=status.HTTP_200_OK)
async def clear_default_taxonomy(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_UPDATE))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear the default embedded taxonomy from a dataset. Requires DATASETS_UPDATE permission."""
    try:
        return await dataset_service.clear_default_taxonomy(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise _http_for_dataset_error(exc)


@router.post("/{dataset_id}/create-variants", status_code=status.HTTP_201_CREATED)
async def create_dataset_variants_from_taxonomies(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_CREATE))],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create separate dataset variants from linked taxonomies.

    For each linked taxonomy, creates a new dataset with the same name but
    that taxonomy's classes. Returns list of created dataset IDs.
    Requires DATASETS_CREATE permission.
    """
    try:
        return await dataset_service.create_variants_from_taxonomies(db, dataset_id)
    except (DatasetNotFoundError, DatasetValidationError) as exc:
        raise _http_for_dataset_error(exc)
