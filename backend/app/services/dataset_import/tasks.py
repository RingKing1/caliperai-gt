"""Task creation/lookup helpers used during scene import."""
from uuid import UUID

from sqlalchemy import select
from asyncpg import Range as PgRange
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Scene, Task

from app.services.dataset_import.naming import generate_smart_task_name


def frame_range_to_postgres(start: int, end: int) -> PgRange:
    """Convert frame range to PostgreSQL INT4RANGE format."""
    return PgRange(start, end + 1)
async def get_or_create_scene_import_task(
    db: AsyncSession,
    scene: Scene,
    assignee_id: UUID,
    frame_count: int,
    description: str,
) -> Task:
    """Pick the task that uploaded annotations should land in.

    Prefer the scene's selected taxonomy task when available so imported
    annotations show up in the same task the UI opens by default. Only create a
    generic fallback task when the scene has no existing tasks.
    """
    result = await db.execute(
        select(Task)
        .where(Task.scene_id == scene.id, Task.is_deleted == False)
        .order_by(Task.created_at.asc())
    )
    existing_tasks = list(result.scalars().all())

    if scene.selected_taxonomy_id:
        for existing_task in existing_tasks:
            if existing_task.taxonomy_id == scene.selected_taxonomy_id:
                return existing_task

    for existing_task in existing_tasks:
        if existing_task.taxonomy_id is not None:
            return existing_task

    if existing_tasks:
        return existing_tasks[0]

    from asyncpg import Range as PgRange

    smart_task_name = generate_smart_task_name(scene.name, frame_count, "Annot")
    task = Task(
        scene_id=scene.id,
        name=smart_task_name,
        description=description,
        assignee_id=assignee_id,
        frame_range=PgRange(0, frame_count) if frame_count > 0 else PgRange(0, 1),
    )
    db.add(task)
    await db.flush()
    return task


