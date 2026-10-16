"""Dataset domain service: CRUD, taxonomy linking and task provisioning.

Extracted from ``app/api/v1/endpoints/datasets.py`` so endpoints stay thin
(auth + HTTP mapping). Functions raise plain domain exceptions instead of
``HTTPException``; the endpoints translate them.
"""
from typing import Any
from uuid import UUID

from asyncpg import Range as PgRange
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.models import (
    Campaign,
    Dataset,
    Scene,
    Task,
    TaskStage,
    TaskStatus,
    Taxonomy,
    dataset_taxonomy_association,
)
from app.schemas.schemas import DatasetCreate, DatasetUpdate

# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class DatasetServiceError(Exception):
    """Base class for dataset-domain errors."""


class DatasetNotFoundError(DatasetServiceError):
    def __init__(self, dataset_id: Any):
        self.dataset_id = dataset_id
        super().__init__(f"Dataset {dataset_id} not found")


class CampaignNotFoundError(DatasetServiceError):
    def __init__(self, campaign_id: Any):
        self.campaign_id = campaign_id
        super().__init__(f"Campaign {campaign_id} not found")


class TaxonomyNotFoundError(DatasetServiceError):
    def __init__(self, taxonomy_id: Any):
        self.taxonomy_id = taxonomy_id
        super().__init__(f"Taxonomy {taxonomy_id} not found")


class DatasetConflictError(DatasetServiceError):
    pass


class DatasetValidationError(DatasetServiceError):
    pass


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def compute_dataset_stats(scenes: list[Scene]) -> dict[str, int]:
    """Aggregate frame/task counters over a list of active scenes."""
    return {
        "scene_count": len(scenes),
        "total_frames": sum(s.frame_count for s in scenes),
        "total_tasks": sum(len(s.tasks) for s in scenes),
        "pending_tasks": sum(
            1 for s in scenes for t in s.tasks if t.status == "pending"
        ),
        "in_progress_tasks": sum(
            1 for s in scenes for t in s.tasks if t.status == "in_progress"
        ),
        "completed_tasks": sum(
            1 for s in scenes for t in s.tasks if t.status == "completed"
        ),
    }


def make_scene_taxonomy_task(scene: Scene, taxonomy_id: UUID, taxonomy_name: str) -> Task:
    """Build the default pending annotation task for a scene/taxonomy pair."""
    return Task(
        scene_id=scene.id,
        taxonomy_id=taxonomy_id,
        name=f"{scene.name} - {taxonomy_name}",
        status=TaskStatus.PENDING.value,
        stage=TaskStage.ANNOTATION.value,
        frame_range=PgRange(0, scene.frame_count),
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _get_active_dataset(
    db: AsyncSession, dataset_id: UUID, *, with_taxonomies: bool = False
) -> Dataset:
    query = select(Dataset).where(
        Dataset.id == dataset_id,
        Dataset.is_deleted == False,  # noqa: E712
    )
    if with_taxonomies:
        query = query.options(selectinload(Dataset.taxonomies))
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise DatasetNotFoundError(dataset_id)
    return dataset


async def auto_create_tasks_for_scene(db: AsyncSession, scene: Scene) -> None:
    """Create one pending task per linked taxonomy for a newly created scene."""
    linked = await db.execute(
        select(dataset_taxonomy_association.c.taxonomy_id, Taxonomy.name)
        .join(
            Taxonomy,
            Taxonomy.id == dataset_taxonomy_association.c.taxonomy_id,
        )
        .where(
            dataset_taxonomy_association.c.dataset_id == scene.dataset_id,
            Taxonomy.is_deleted == False,  # noqa: E712
        )
    )
    for row in linked.all():
        db.add(make_scene_taxonomy_task(scene, row.taxonomy_id, row.name))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_dataset(db: AsyncSession, dataset_in: DatasetCreate) -> Dataset:
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == dataset_in.campaign_id,
            Campaign.is_deleted == False,  # noqa: E712
        )
    )
    if not result.scalar_one_or_none():
        raise CampaignNotFoundError(dataset_in.campaign_id)

    existing_result = await db.execute(
        select(Dataset).where(
            Dataset.campaign_id == dataset_in.campaign_id,
            Dataset.name == dataset_in.name,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    if existing_result.scalar_one_or_none():
        raise DatasetConflictError(
            f"A dataset with the name '{dataset_in.name}' already exists in this campaign"
        )

    dataset = Dataset(
        campaign_id=dataset_in.campaign_id,
        name=dataset_in.name,
        description=dataset_in.description,
        taxonomy=dataset_in.taxonomy.model_dump(),
        sensor_config=dataset_in.sensor_config.model_dump(),
    )
    db.add(dataset)
    await db.flush()
    await db.refresh(dataset)
    return dataset


async def list_datasets(
    db: AsyncSession,
    campaign_id: UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[Dataset]:
    query = (
        select(Dataset)
        .where(Dataset.is_deleted == False)  # noqa: E712
        .options(selectinload(Dataset.taxonomies))
    )
    if campaign_id:
        query = query.where(Dataset.campaign_id == campaign_id)
    query = query.order_by(Dataset.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_dataset(db: AsyncSession, dataset_id: UUID) -> Dataset:
    return await _get_active_dataset(db, dataset_id, with_taxonomies=True)


async def get_dataset_detail(db: AsyncSession, dataset_id: UUID) -> dict:
    query = (
        select(Dataset)
        .where(
            Dataset.id == dataset_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
        .options(
            selectinload(Dataset.taxonomies),
            selectinload(Dataset.scenes)
            .selectinload(Scene.tasks)
            .selectinload(Task.taxonomy),
        )
    )
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise DatasetNotFoundError(dataset_id)

    active_scenes = [s for s in dataset.scenes if not s.is_deleted]
    for scene in active_scenes:
        scene.tasks = [t for t in scene.tasks if not t.is_deleted]

    return {
        "id": dataset.id,
        "campaign_id": dataset.campaign_id,
        "name": dataset.name,
        "description": dataset.description,
        "taxonomy": dataset.taxonomy,
        "sensor_config": dataset.sensor_config,
        "custom_metadata": dataset.custom_metadata,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "taxonomies": [t for t in dataset.taxonomies if not t.is_deleted],
        "scenes": active_scenes,
        "stats": compute_dataset_stats(active_scenes),
    }


async def update_dataset(
    db: AsyncSession, dataset_id: UUID, dataset_in: DatasetUpdate
) -> Dataset:
    dataset = await _get_active_dataset(db, dataset_id)

    update_data = dataset_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if hasattr(value, "model_dump"):
                value = value.model_dump()
            setattr(dataset, field, value)

    await db.flush()
    await db.refresh(dataset)
    return dataset


async def soft_delete_dataset(db: AsyncSession, dataset_id: UUID) -> None:
    dataset = await _get_active_dataset(db, dataset_id)
    dataset.is_deleted = True
    await db.flush()


# ---------------------------------------------------------------------------
# Embedded / linked taxonomies
# ---------------------------------------------------------------------------


async def get_embedded_taxonomy(db: AsyncSession, dataset_id: UUID) -> dict:
    result = await db.execute(
        select(Dataset.taxonomy).where(
            Dataset.id == dataset_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    taxonomy = result.scalar_one_or_none()
    if taxonomy is None:
        raise DatasetNotFoundError(dataset_id)
    return taxonomy


async def list_taxonomies(db: AsyncSession, dataset_id: UUID) -> list[Taxonomy]:
    dataset = await _get_active_dataset(db, dataset_id, with_taxonomies=True)
    return [t for t in dataset.taxonomies if not t.is_deleted]


async def link_taxonomy(
    db: AsyncSession, dataset_id: UUID, taxonomy_id: UUID
) -> dict:
    dataset = await _get_active_dataset(db, dataset_id)

    result = await db.execute(
        select(Taxonomy).where(
            Taxonomy.id == taxonomy_id,
            Taxonomy.is_deleted == False,  # noqa: E712
        )
    )
    taxonomy = result.scalar_one_or_none()
    if not taxonomy:
        raise TaxonomyNotFoundError(taxonomy_id)

    result = await db.execute(
        select(dataset_taxonomy_association).where(
            dataset_taxonomy_association.c.dataset_id == dataset_id,
            dataset_taxonomy_association.c.taxonomy_id == taxonomy_id,
        )
    )
    if result.first():
        raise DatasetValidationError(
            "Taxonomy is already associated with this dataset"
        )

    effective_mode = taxonomy.annotation_mode

    primary_result = await db.execute(
        select(dataset_taxonomy_association).where(
            dataset_taxonomy_association.c.dataset_id == dataset_id,
            dataset_taxonomy_association.c.mode == effective_mode,
            dataset_taxonomy_association.c.is_primary == True,  # noqa: E712
        )
    )
    has_existing_primary = primary_result.first() is not None
    is_primary = not has_existing_primary

    await db.execute(
        dataset_taxonomy_association.insert().values(
            dataset_id=dataset_id,
            taxonomy_id=taxonomy_id,
            mode=effective_mode,
            is_primary=is_primary,
        )
    )

    current_taxonomy = dataset.taxonomy or {}
    current_classes = current_taxonomy.get("classes", [])

    if not current_classes and taxonomy.classes:
        dataset.taxonomy = {
            "classes": (
                taxonomy.classes if isinstance(taxonomy.classes, list) else []
            ),
            "skeletons": current_taxonomy.get("skeletons", {}),
            "annotation_rules": current_taxonomy.get("annotation_rules", {}),
        }

    await db.flush()

    scenes_result = await db.execute(
        select(Scene).where(
            Scene.dataset_id == dataset_id,
            Scene.is_deleted == False,  # noqa: E712
        )
    )
    scenes = scenes_result.scalars().all()
    for scene in scenes:
        db.add(make_scene_taxonomy_task(scene, taxonomy_id, taxonomy.name))

    await db.flush()

    return {
        "message": "Taxonomy linked successfully",
        "dataset_id": str(dataset_id),
        "taxonomy_id": str(taxonomy_id),
    }


async def create_tasks_for_taxonomy(
    db: AsyncSession, dataset_id: UUID, taxonomy_id: UUID
) -> dict:
    """Create tasks for scenes missing one for this taxonomy."""
    await _get_active_dataset(db, dataset_id)

    taxonomy_result = await db.execute(
        select(Taxonomy).where(
            Taxonomy.id == taxonomy_id,
            Taxonomy.is_deleted == False,  # noqa: E712
        )
    )
    taxonomy = taxonomy_result.scalar_one_or_none()
    if not taxonomy:
        raise TaxonomyNotFoundError(taxonomy_id)

    scenes_result = await db.execute(
        select(Scene).where(
            Scene.dataset_id == dataset_id,
            Scene.is_deleted == False,  # noqa: E712
        )
    )
    scenes = scenes_result.scalars().all()

    existing_result = await db.execute(
        select(Task.scene_id).where(
            Task.taxonomy_id == taxonomy_id,
            Task.scene_id.in_([s.id for s in scenes]),
            Task.is_deleted == False,  # noqa: E712
        )
    )
    existing_scene_ids = {row[0] for row in existing_result.all()}

    created = 0
    for scene in scenes:
        if scene.id in existing_scene_ids:
            continue
        db.add(make_scene_taxonomy_task(scene, taxonomy_id, taxonomy.name))
        created += 1

    await db.flush()
    return {"created": created, "skipped": len(scenes) - created}


async def unlink_taxonomy(db: AsyncSession, dataset_id: UUID, taxonomy_id: UUID) -> None:
    await _get_active_dataset(db, dataset_id)

    scene_id_subq = (
        select(Scene.id)
        .where(
            Scene.dataset_id == dataset_id,
            Scene.is_deleted == False,  # noqa: E712
        )
        .scalar_subquery()
    )
    await db.execute(
        delete(Task).where(
            Task.scene_id.in_(scene_id_subq),
            Task.taxonomy_id == taxonomy_id,
        )
    )

    await db.execute(
        delete(dataset_taxonomy_association).where(
            dataset_taxonomy_association.c.dataset_id == dataset_id,
            dataset_taxonomy_association.c.taxonomy_id == taxonomy_id,
        )
    )
    await db.flush()


async def clear_default_taxonomy(db: AsyncSession, dataset_id: UUID) -> dict:
    dataset = await _get_active_dataset(db, dataset_id)
    dataset.taxonomy = {"classes": [], "skeletons": {}, "annotation_rules": {}}
    await db.flush()
    return {
        "message": "Default taxonomy cleared",
        "dataset_id": str(dataset_id),
    }


async def create_variants_from_taxonomies(
    db: AsyncSession, dataset_id: UUID
) -> dict:
    """Create one dataset variant per linked taxonomy.

    For each linked taxonomy, creates a new dataset with the same name but
    that taxonomy's classes. Returns created/skipped dataset summaries.
    """
    query = (
        select(Dataset)
        .options(selectinload(Dataset.taxonomies))
        .where(
            Dataset.id == dataset_id,
            Dataset.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(query)
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise DatasetNotFoundError(dataset_id)

    linked_taxonomies = [t for t in dataset.taxonomies if not t.is_deleted]

    if not linked_taxonomies:
        raise DatasetValidationError("No taxonomies linked to this dataset")

    created_datasets = []
    skipped_datasets = []

    for taxonomy in linked_taxonomies:
        variant_name = f"{dataset.name} ({taxonomy.name})"

        existing_result = await db.execute(
            select(Dataset).where(
                Dataset.campaign_id == dataset.campaign_id,
                Dataset.name == variant_name,
                Dataset.is_deleted == False,  # noqa: E712
            )
        )
        if existing_result.scalar_one_or_none():
            skipped_datasets.append(
                {
                    "name": variant_name,
                    "taxonomy_name": taxonomy.name,
                    "reason": "A dataset with this name already exists",
                }
            )
            continue

        new_dataset = Dataset(
            campaign_id=dataset.campaign_id,
            name=variant_name,
            description=f"{dataset.description or ''}\n\nVariant created with taxonomy: {taxonomy.name} v{taxonomy.version}".strip(),
            taxonomy={
                "classes": (
                    taxonomy.classes if isinstance(taxonomy.classes, list) else []
                ),
                "skeletons": {},
                "annotation_rules": {},
            },
            sensor_config=dataset.sensor_config,
        )
        db.add(new_dataset)
        await db.flush()
        await db.refresh(new_dataset)

        await db.execute(
            dataset_taxonomy_association.insert().values(
                dataset_id=new_dataset.id,
                taxonomy_id=taxonomy.id,
            )
        )

        created_datasets.append(
            {
                "id": str(new_dataset.id),
                "name": new_dataset.name,
                "taxonomy_id": str(taxonomy.id),
                "taxonomy_name": taxonomy.name,
            }
        )

    await db.flush()

    message = f"Created {len(created_datasets)} dataset variants"
    if skipped_datasets:
        message += f", skipped {len(skipped_datasets)} (duplicate names)"

    return {
        "message": message,
        "original_dataset_id": str(dataset_id),
        "created_datasets": created_datasets,
        "skipped_datasets": skipped_datasets,
    }
