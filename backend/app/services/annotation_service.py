"""
Annotation domain service.

Single source of truth for the write-path business rules shared by every
annotation modality (legacy generic table, 2D camera, 3D LiDAR, 4D temporal,
fusion):

* task auto-transition (pending/assigned -> in_progress) on first write
* "manual source implies human-verified" derivation, with explicit override
* ORM construction / upsert rules per modality table

The HTTP layer (endpoints) owns auth dependencies, 404/400 mapping and
response models. This module never raises HTTP exceptions.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Frame,
    Task,
    TaskStatus,
)
from app.schemas.schemas import (
    Annotation2DCreate,
    Annotation2DUpdate,
    Annotation3DCreate,
    Annotation3DUpdate,
    Annotation4DCreate,
    Annotation4DUpdate,
    AnnotationCreate,
    AnnotationFusionCreate,
    AnnotationFusionUpdate,
    AnnotationUpdate,
)
from app.services.workflow_service import WorkflowError, WorkflowService

# Sources that represent human-created annotations per modality.
MANUAL_SOURCES: dict[str, set[str]] = {
    "generic": {"manual"},
    "2d": {"manual_2d"},
    "3d": {"manual", "manual_3d"},
    "fusion": {"manual_fusion"},
}


def enum_value(value: Any) -> Any:
    """Return the raw value of an enum member, or the value itself."""
    return value.value if hasattr(value, "value") else value


def resolve_is_verified(
    source: Any,
    modality: str,
    explicit: Optional[bool] = None,
) -> bool:
    """Resolve the verification flag for a newly created annotation.

    An explicit client value always wins (e.g. interpolated frames saved as
    unverified); otherwise any modality-specific manual source counts as
    human-verified.
    """
    if explicit is not None:
        return explicit
    return enum_value(source) in MANUAL_SOURCES[modality]


class AnnotationService:
    """Business rules for every annotation table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ loaders
    async def get_task(self, task_id: UUID) -> Optional[Task]:
        """Fetch a task by primary key (soft-deleted tasks included)."""
        return await self.db.get(Task, task_id)

    async def get_active_task(self, task_id: UUID) -> Optional[Task]:
        """Fetch a task, excluding soft-deleted ones."""
        result = await self.db.execute(
            select(Task).where(Task.id == task_id, Task.is_deleted == False)  # noqa: E712
        )
        return result.scalar_one_or_none()

    async def get_frame(self, frame_id: UUID) -> Optional[Frame]:
        """Fetch a frame by primary key."""
        return await self.db.get(Frame, frame_id)

    # ------------------------------------------------------------ workflow hook
    async def maybe_start_work(
        self,
        task: Task,
        changed_by_id: UUID,
    ) -> bool:
        """Transition a fresh task (pending/assigned) to in_progress.

        Returns True when the transition ran. Invalid transitions are
        swallowed to keep annotation writes non-blocking.
        """
        if task.status not in (
            TaskStatus.PENDING.value,
            TaskStatus.ASSIGNED.value,
        ):
            return False
        try:
            await WorkflowService(self.db).start_work(
                task, changed_by_id=changed_by_id
            )
            return True
        except WorkflowError:
            return False

    async def transition_tasks_once(
        self,
        task_ids: list[UUID],
        changed_by_id: UUID,
    ) -> None:
        """Best-effort transition for a batch of distinct task IDs."""
        seen: set[UUID] = set()
        for task_id in task_ids:
            if task_id in seen:
                continue
            seen.add(task_id)
            task = await self.db.get(Task, task_id)
            if task:
                await self.maybe_start_work(task, changed_by_id)

    # ============================================================ generic table
    @staticmethod
    def build_generic(data: AnnotationCreate) -> Annotation:
        source_value = enum_value(data.source)
        return Annotation(
            task_id=data.task_id,
            frame_id=data.frame_id,
            track_id=data.track_id,
            type=enum_value(data.type),
            class_id=data.class_id,
            data=data.data,
            attributes=data.attributes,
            source=source_value,
            taxonomy_id=data.taxonomy_id,
            is_verified=resolve_is_verified(source_value, "generic"),
        )

    async def create_generic(self, data: AnnotationCreate) -> Annotation:
        annotation = self.build_generic(data)
        self.db.add(annotation)
        await self.db.flush()
        await self.db.refresh(annotation)
        return annotation

    async def bulk_create_generic(
        self,
        items: list[AnnotationCreate],
        changed_by_id: UUID,
    ) -> Tuple[int, list[dict]]:
        """Best-effort bulk insert; per-item failures are collected, not raised."""
        success_count = 0
        errors: list[dict] = []
        transitioned: set[UUID] = set()

        for index, item in enumerate(items):
            try:
                if item.task_id not in transitioned:
                    task = await self.db.get(Task, item.task_id)
                    if task:
                        await self.maybe_start_work(task, changed_by_id)
                        transitioned.add(item.task_id)

                self.db.add(self.build_generic(item))
                success_count += 1
            except Exception as exc:
                errors.append({"index": index, "error": str(exc)})

        await self.db.flush()
        return success_count, errors

    async def update_generic(
        self,
        annotation_id: UUID,
        update: AnnotationUpdate,
    ) -> Optional[Annotation]:
        """Update a generic annotation.

        Editing geometry of an auto annotation promotes it to manual.
        """
        annotation = await self.db.get(Annotation, annotation_id)
        if annotation is None:
            return None

        update_data = update.model_dump(exclude_unset=True)

        if "data" in update_data and annotation.source != "manual":
            annotation.source = "manual"
            annotation.is_verified = True

        for field, value in update_data.items():
            setattr(annotation, field, value)

        await self.db.flush()
        await self.db.refresh(annotation)
        return annotation

    # ==================================================================== 3D
    @staticmethod
    def build_3d(
        data: Annotation3DCreate,
        annotation_id: Optional[UUID] = None,
    ) -> Annotation3D:
        return Annotation3D(
            id=annotation_id or data.id or uuid4(),
            task_id=data.task_id,
            frame_id=data.frame_id,
            track_id=data.track_id,
            type=data.type,
            class_id=data.class_id,
            taxonomy_id=data.taxonomy_id,
            data=data.data,
            attributes=data.attributes,
            source=data.source,
            is_verified=resolve_is_verified(
                data.source, "3d", explicit=data.is_verified
            ),
            is_keyframe=data.is_keyframe,
            is_static=data.is_static,
        )

    @staticmethod
    def apply_3d(existing: Annotation3D, data: Annotation3DCreate) -> Annotation3D:
        """Overwrite an existing 3D row during a client-id upsert."""
        existing.task_id = data.task_id
        existing.frame_id = data.frame_id
        existing.track_id = data.track_id
        existing.type = data.type
        existing.class_id = data.class_id
        existing.taxonomy_id = data.taxonomy_id
        existing.data = data.data
        existing.attributes = data.attributes
        existing.source = data.source
        existing.is_verified = resolve_is_verified(
            data.source, "3d", explicit=data.is_verified
        )
        existing.is_keyframe = data.is_keyframe
        existing.is_static = data.is_static
        return existing

    async def create_3d(self, data: Annotation3DCreate) -> Annotation3D:
        annotation = self.build_3d(data)
        self.db.add(annotation)
        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    async def bulk_upsert_3d(
        self,
        items: list[Annotation3DCreate],
        changed_by_id: UUID,
    ) -> list[Annotation3D]:
        """Create or overwrite 3D annotations keyed by client-provided id."""
        results: list[Annotation3D] = []
        transitioned: set[tuple[UUID, Optional[UUID]]] = set()

        for item in items:
            annotation_id = item.id or uuid4()
            existing = await self.db.get(Annotation3D, annotation_id)

            if existing:
                results.append(self.apply_3d(existing, item))
                continue

            transition_key = (item.task_id, item.taxonomy_id)
            if transition_key not in transitioned:
                task = await self.db.get(Task, item.task_id)
                if task:
                    await self.maybe_start_work(task, changed_by_id)
                    transitioned.add(transition_key)

            annotation = self.build_3d(item, annotation_id)
            self.db.add(annotation)
            results.append(annotation)

        await self.db.commit()
        for annotation in results:
            await self.db.refresh(annotation)
        return results

    async def update_3d(
        self,
        annotation_id: UUID,
        update: Annotation3DUpdate,
    ) -> Optional[Annotation3D]:
        """Update a 3D annotation; geometry edits promote it to manual_3d."""
        annotation = await self.db.get(Annotation3D, annotation_id)
        if annotation is None:
            return None

        update_data = update.model_dump(exclude_unset=True)

        if "data" in update_data and annotation.source != "manual_3d":
            annotation.source = "manual_3d"
            annotation.is_verified = True

        for key, value in update_data.items():
            setattr(annotation, key, value)

        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    # ==================================================================== 2D
    @staticmethod
    def build_2d(
        data: Annotation2DCreate,
        annotation_id: Optional[UUID] = None,
    ) -> Annotation2D:
        return Annotation2D(
            id=annotation_id or data.id or uuid4(),
            task_id=data.task_id,
            frame_id=data.frame_id,
            camera_id=data.camera_id,
            track_id=data.track_id,
            type=data.type,
            class_id=data.class_id,
            taxonomy_id=data.taxonomy_id,
            data=data.data,
            attributes=data.attributes,
            source=data.source,
            is_verified=resolve_is_verified(data.source, "2d"),
        )

    @staticmethod
    def apply_2d(existing: Annotation2D, data: Annotation2DCreate) -> Annotation2D:
        """Overwrite an existing 2D row during a client-id upsert.

        Verification state is re-derived from the incoming source, matching
        the 3D upsert rule (manual source implies human-verified).
        """
        existing.frame_id = data.frame_id
        existing.camera_id = data.camera_id
        existing.track_id = data.track_id
        existing.type = data.type
        existing.class_id = data.class_id
        existing.taxonomy_id = data.taxonomy_id
        existing.data = data.data
        existing.attributes = data.attributes
        existing.source = data.source
        existing.is_verified = resolve_is_verified(data.source, "2d")
        return existing

    async def create_2d(self, data: Annotation2DCreate) -> Annotation2D:
        annotation = self.build_2d(data)
        self.db.add(annotation)
        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    async def bulk_upsert_2d(
        self,
        items: list[Annotation2DCreate],
        changed_by_id: UUID,
    ) -> list[Annotation2D]:
        """Create or overwrite 2D annotations keyed by client-provided id."""
        results: list[Annotation2D] = []
        transitioned: set[tuple[UUID, Optional[UUID]]] = set()

        for item in items:
            annotation_id = item.id or uuid4()

            transition_key = (item.task_id, item.taxonomy_id)
            if transition_key not in transitioned:
                task = await self.db.get(Task, item.task_id)
                if task:
                    await self.maybe_start_work(task, changed_by_id)
                    transitioned.add(transition_key)

            existing = await self.db.get(Annotation2D, annotation_id)
            if existing:
                results.append(self.apply_2d(existing, item))
            else:
                annotation = self.build_2d(item, annotation_id)
                self.db.add(annotation)
                results.append(annotation)

        await self.db.commit()
        for annotation in results:
            await self.db.refresh(annotation)
        return results

    async def update_2d(
        self,
        annotation_id: UUID,
        update: Annotation2DUpdate,
    ) -> Optional[Annotation2D]:
        annotation = await self.db.get(Annotation2D, annotation_id)
        if annotation is None:
            return None

        for key, value in update.model_dump(exclude_unset=True).items():
            setattr(annotation, key, value)

        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    # ==================================================================== 4D
    @staticmethod
    def _normalize_4d(
        frame_ids: Optional[list[UUID]],
        frame_data: Optional[dict],
    ) -> Tuple[list[str], dict]:
        frame_ids_str = [str(fid) for fid in frame_ids] if frame_ids else []
        frame_data_str = (
            {str(key): value for key, value in frame_data.items()}
            if frame_data
            else {}
        )
        return frame_ids_str, frame_data_str

    @classmethod
    def build_4d(
        cls,
        data: Annotation4DCreate,
        annotation_id: Optional[UUID] = None,
    ) -> Annotation4D:
        frame_ids_str, frame_data_str = cls._normalize_4d(
            data.frame_ids, data.frame_data
        )
        return Annotation4D(
            id=annotation_id or data.id or uuid4(),
            task_id=data.task_id,
            track_id=data.track_id,
            type=data.type,
            class_id=data.class_id,
            world_data=data.world_data,
            frame_data=frame_data_str,
            frame_ids=frame_ids_str,
            is_static=data.is_static,
            attributes=data.attributes,
            source=data.source,
        )

    async def create_4d(self, data: Annotation4DCreate) -> Annotation4D:
        annotation = self.build_4d(data)
        self.db.add(annotation)
        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    async def bulk_create_4d(
        self,
        items: list[Annotation4DCreate],
        changed_by_id: UUID,
    ) -> list[Annotation4D]:
        results: list[Annotation4D] = []
        transitioned: set[UUID] = set()

        for item in items:
            if item.task_id not in transitioned:
                task = await self.db.get(Task, item.task_id)
                if task:
                    await self.maybe_start_work(task, changed_by_id)
                    transitioned.add(item.task_id)

            annotation = self.build_4d(item)
            self.db.add(annotation)
            results.append(annotation)

        await self.db.commit()
        for annotation in results:
            await self.db.refresh(annotation)
        return results

    async def update_4d(
        self,
        annotation_id: UUID,
        update: Annotation4DUpdate,
    ) -> Optional[Annotation4D]:
        annotation = await self.db.get(Annotation4D, annotation_id)
        if annotation is None:
            return None

        update_data = update.model_dump(exclude_unset=True)

        if update_data.get("frame_ids") is not None:
            update_data["frame_ids"] = [
                str(fid) for fid in update_data["frame_ids"]
            ]
        if update_data.get("frame_data") is not None:
            update_data["frame_data"] = {
                str(key): value
                for key, value in update_data["frame_data"].items()
            }

        for key, value in update_data.items():
            setattr(annotation, key, value)

        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    # ================================================================= fusion
    @staticmethod
    def _normalize_data_2d(raw: Optional[dict]) -> dict:
        data_2d: dict = {}
        if raw:
            for camera_id, projection in raw.items():
                data_2d[camera_id] = (
                    projection.model_dump()
                    if hasattr(projection, "model_dump")
                    else projection
                )
        return data_2d

    @classmethod
    def build_fusion(
        cls,
        data: AnnotationFusionCreate,
        annotation_id: Optional[UUID] = None,
    ) -> AnnotationFusion:
        return AnnotationFusion(
            id=annotation_id or data.id or uuid4(),
            task_id=data.task_id,
            frame_id=data.frame_id,
            track_id=data.track_id,
            type=data.type,
            class_id=data.class_id,
            data_3d=data.data_3d,
            data_2d=cls._normalize_data_2d(data.data_2d),
            attributes=data.attributes,
            source=data.source,
            source_3d_annotation_id=data.source_3d_annotation_id,
            is_verified=resolve_is_verified(data.source, "fusion"),
        )

    async def create_fusion(self, data: AnnotationFusionCreate) -> AnnotationFusion:
        annotation = self.build_fusion(data)
        self.db.add(annotation)
        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    async def update_fusion(
        self,
        annotation_id: UUID,
        update: AnnotationFusionUpdate,
    ) -> Optional[AnnotationFusion]:
        """Update a fusion annotation; 3D geometry edits promote it to manual."""
        annotation = await self.db.get(AnnotationFusion, annotation_id)
        if annotation is None:
            return None

        update_data = update.model_dump(exclude_unset=True)

        if "data_3d" in update_data and annotation.source not in (
            "manual_fusion",
            "manual",
        ):
            annotation.source = "manual_fusion"
            annotation.is_verified = True

        for key, value in update_data.items():
            setattr(annotation, key, value)

        await self.db.commit()
        await self.db.refresh(annotation)
        return annotation

    async def bulk_create_fusion(
        self,
        items: list[AnnotationFusionCreate],
        changed_by_id: UUID,
    ) -> list[AnnotationFusion]:
        results: list[AnnotationFusion] = []
        transitioned: set[UUID] = set()

        for item in items:
            if item.task_id not in transitioned:
                task = await self.db.get(Task, item.task_id)
                if task:
                    await self.maybe_start_work(task, changed_by_id)
                    transitioned.add(item.task_id)

            annotation = self.build_fusion(item)
            self.db.add(annotation)
            results.append(annotation)

        await self.db.commit()
        for annotation in results:
            await self.db.refresh(annotation)
        return results
