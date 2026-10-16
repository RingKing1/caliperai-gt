"""Export Service - Orchestrates task, scene, and dataset export bundles."""
from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Annotation,
    Annotation2D,
    Annotation3D,
    Annotation4D,
    AnnotationFusion,
    Dataset,
    Frame,
    Scene,
    Task,
    Taxonomy,
    Track2D,
)
from app.services.export.archive import (
    add_scene_data_to_zip,
    build_task_export_folder_name,
)
from app.services.export.coco_converter import add_sensor_annotations_to_zip
from app.services.export.merge import merge_overlapping_annotations
from app.services.export.segmentation_exporter import (
    add_segmentation_kitti_to_zip,
    get_segmentation_taxonomy_classes,
)


class ExportNotFoundError(Exception):
    """Raised when an exported entity (Task, Scene, Dataset) does not exist."""


async def get_annotations_for_task(
    db: AsyncSession,
    task_id: UUID,
    taxonomy_id: UUID | None = None,
    annotation_mode: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Get annotations for a task, optionally filtered to a specific taxonomy."""
    annotations: dict[str, list[dict[str, Any]]] = {
        "cuboids_3d": [],
        "boxes_2d": [],
        "annotations_4d": [],
        "annotations_fusion": [],
        "annotations_legacy": [],
        "tracks_2d": [],
    }

    if annotation_mode == "segmentation_3d":
        return annotations

    where_3d = [Annotation3D.task_id == task_id]
    if taxonomy_id is not None:
        where_3d.append(Annotation3D.taxonomy_id == taxonomy_id)
    stmt = (
        select(Annotation3D, Frame)
        .join(Frame, Annotation3D.frame_id == Frame.id)
        .where(*where_3d)
    )
    result = await db.execute(stmt)
    for ann, frame in result.all():
        data = ann.data or {}
        center = data.get("center", {})
        dimensions = data.get("dimensions", {})
        rotation = data.get("rotation", {})
        annotations["cuboids_3d"].append({
            "id": str(ann.id),
            "track_id": str(ann.track_id) if ann.track_id else None,
            "frame_index": frame.frame_index,
            "class_id": ann.class_id,
            "position": {
                "x": center.get("x", 0),
                "y": center.get("y", 0),
                "z": center.get("z", 0),
            },
            "dimensions": {
                "length": dimensions.get("length", 0),
                "width": dimensions.get("width", 0),
                "height": dimensions.get("height", 0),
            },
            "rotation": {
                "yaw": rotation.get("yaw", 0),
                "pitch": rotation.get("pitch", 0),
                "roll": rotation.get("roll", 0),
            },
            "attributes": ann.attributes or {},
            "source": ann.source,
            "confidence": data.get("confidence", 1.0),
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    where_2d = [Annotation2D.task_id == task_id]
    if taxonomy_id is not None:
        where_2d.append(Annotation2D.taxonomy_id == taxonomy_id)
    stmt = (
        select(Annotation2D, Frame)
        .join(Frame, Annotation2D.frame_id == Frame.id)
        .where(*where_2d)
    )
    result = await db.execute(stmt)
    for ann, frame in result.all():
        annotations["boxes_2d"].append({
            "id": str(ann.id),
            "track_id": str(ann.track_id) if ann.track_id else None,
            "frame_id": str(ann.frame_id),
            "frame_index": frame.frame_index,
            "camera_id": ann.camera_id,
            "class_id": ann.class_id,
            "type": ann.type,
            "data": ann.data,
            "attributes": ann.attributes or {},
            "source": ann.source,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    stmt = select(Annotation4D).where(Annotation4D.task_id == task_id)
    result = await db.execute(stmt)
    for ann in result.scalars().all():
        annotations["annotations_4d"].append({
            "id": str(ann.id),
            "track_id": str(ann.track_id) if ann.track_id else None,
            "class_id": ann.class_id,
            "frame_range": {"start": ann.frame_start, "end": ann.frame_end},
            "position": {"x": ann.position_x, "y": ann.position_y, "z": ann.position_z},
            "dimensions": {
                "length": ann.dimension_length,
                "width": ann.dimension_width,
                "height": ann.dimension_height,
            },
            "rotation": {
                "yaw": ann.rotation_yaw,
                "pitch": ann.rotation_pitch,
                "roll": ann.rotation_roll,
            },
            "is_static": ann.is_static,
            "attributes": ann.attributes or {},
            "source": ann.source,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    stmt = select(AnnotationFusion).where(AnnotationFusion.task_id == task_id)
    result = await db.execute(stmt)
    for ann in result.scalars().all():
        annotations["annotations_fusion"].append({
            "id": str(ann.id),
            "track_id": str(ann.track_id) if ann.track_id else None,
            "frame_index": ann.frame_index,
            "class_id": ann.class_id,
            "cuboid_3d": {
                "position": {"x": ann.position_x, "y": ann.position_y, "z": ann.position_z},
                "dimensions": {
                    "length": ann.dimension_length,
                    "width": ann.dimension_width,
                    "height": ann.dimension_height,
                },
                "rotation": {
                    "yaw": ann.rotation_yaw,
                    "pitch": ann.rotation_pitch,
                    "roll": ann.rotation_roll,
                },
            },
            "camera_projections": ann.camera_projections or {},
            "attributes": ann.attributes or {},
            "source": ann.source,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    where_leg = [Annotation.task_id == task_id]
    if taxonomy_id is not None:
        where_leg.append(Annotation.taxonomy_id == taxonomy_id)
    stmt = select(Annotation).where(*where_leg)
    result = await db.execute(stmt)
    for ann in result.scalars().all():
        annotations["annotations_legacy"].append({
            "id": str(ann.id),
            "track_id": str(ann.track_id) if ann.track_id else None,
            "frame_id": str(ann.frame_id) if ann.frame_id else None,
            "type": ann.type,
            "class_id": ann.class_id,
            "data": ann.data,
            "attributes": ann.attributes or {},
            "source": ann.source,
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        })

    stmt = select(Track2D).where(Track2D.task_id == task_id)
    result = await db.execute(stmt)
    for tr in result.scalars().all():
        annotations["tracks_2d"].append({
            "id": str(tr.id),
            "camera_id": tr.camera_id,
            "class_id": tr.class_id,
            "name": tr.name,
            "color": tr.color,
            "start_frame_index": tr.start_frame_index,
            "end_frame_index": tr.end_frame_index,
            "is_interpolated": tr.is_interpolated,
            "is_complete": tr.is_complete,
            "attributes": tr.attributes or {},
        })

    return annotations


def get_scene_metadata(scene: Scene) -> dict[str, Any]:
    """Get scene metadata for export."""
    return {
        "id": str(scene.id),
        "name": scene.name,
        "description": scene.description,
        "frame_count": scene.frame_count,
        "fps": scene.fps,
        "metadata": scene.scene_metadata,
        "calibration": scene.calibration,
        "storage_paths": scene.storage_paths,
        "created_at": scene.created_at.isoformat() if scene.created_at else None,
    }


async def get_frames_metadata(db: AsyncSession, scene_id: UUID) -> list[dict[str, Any]]:
    """Get all frames metadata for a scene."""
    stmt = select(Frame).where(Frame.scene_id == scene_id).order_by(Frame.frame_index)
    result = await db.execute(stmt)
    frames: list[dict[str, Any]] = []
    for frame in result.scalars().all():
        frames.append({
            "id": str(frame.id),
            "frame_index": frame.frame_index,
            "timestamp": frame.timestamp,
            "file_paths": frame.file_paths,
            "ego_pose": frame.ego_pose,
        })
    return frames


async def export_task_bundle(
    db: AsyncSession,
    *,
    task_id: UUID,
    include_data: bool = False,
    format: Literal["json", "coco"] = "coco",
    taxonomy_id: UUID | None = None,
    username: str,
) -> tuple[io.BytesIO, str, str]:
    """Build task export bundle.

    Returns:
        tuple of (buffer, media_type, filename)
    """
    task = await db.get(Task, task_id)
    if not task:
        raise ExportNotFoundError("Task not found")

    scene = await db.get(Scene, task.scene_id)
    if not scene:
        raise ExportNotFoundError("Scene not found")

    dataset = await db.get(Dataset, scene.dataset_id)
    taxonomy = dataset.taxonomy if dataset else {}

    annotation_mode: str | None = None
    if taxonomy_id is not None:
        tax_obj = await db.get(Taxonomy, taxonomy_id)
        if tax_obj:
            annotation_mode = tax_obj.annotation_mode

    scene_classes = await get_segmentation_taxonomy_classes(db, scene.dataset_id)

    annotations = await get_annotations_for_task(
        db, task_id, taxonomy_id=taxonomy_id, annotation_mode=annotation_mode
    )
    frames_data = await get_frames_metadata(db, scene.id)

    metadata: dict[str, Any] = {
        "export_info": {
            "format_version": "2.0",
            "format": format,
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": username,
            "export_type": "task",
            "taxonomy_id": str(taxonomy_id) if taxonomy_id else None,
            "annotation_mode": annotation_mode,
        },
        "task": {
            "id": str(task.id),
            "status": task.status,
            "stage": task.stage,
            "frame_range": {
                "start": task.frame_range.lower if task.frame_range else 0,
                "end": (task.frame_range.upper - 1) if task.frame_range else 0,
            },
        },
        "scene": get_scene_metadata(scene),
        "dataset": {
            "id": str(dataset.id) if dataset else None,
            "name": dataset.name if dataset else None,
        },
        "taxonomy": taxonomy,
        "frames": frames_data,
    }

    if format == "coco":
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if annotation_mode != "segmentation_3d":
                annotation_counts = add_sensor_annotations_to_zip(
                    zf, annotations, frames_data, taxonomy, scene, prefix="annotations"
                )
                metadata["annotation_counts"] = annotation_counts

            if include_data:
                add_scene_data_to_zip(zf, scene, frames_data, prefix="data")

            if taxonomy_id is None or annotation_mode == "segmentation_3d":
                add_segmentation_kitti_to_zip(
                    zf,
                    scene,
                    frames_data,
                    taxonomy,
                    prefix="annotations",
                    scene_classes=scene_classes,
                )

            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

        zip_buffer.seek(0)
        filename = (
            f"task_{task_id}_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        )
        return zip_buffer, "application/zip", filename
    else:
        export_data = {
            **metadata,
            "annotations": annotations,
        }

        if include_data:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("labels.json", json.dumps(export_data, indent=2))
                add_scene_data_to_zip(zf, scene, frames_data, prefix="data")

            zip_buffer.seek(0)
            filename = (
                f"task_{task_id}_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
            )
            return zip_buffer, "application/zip", filename
        else:
            filename = (
                f"task_{task_id}_labels_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
            )
            buffer = io.BytesIO(json.dumps(export_data, indent=2).encode())
            return buffer, "application/json", filename


async def export_scene_bundle(
    db: AsyncSession,
    *,
    scene_id: UUID,
    include_data: bool = False,
    format: Literal["json", "coco"] = "coco",
    taxonomy_id: UUID | None = None,
    username: str,
) -> tuple[io.BytesIO, str, str]:
    """Build scene export bundle across all tasks."""
    scene = await db.get(Scene, scene_id)
    if not scene:
        raise ExportNotFoundError("Scene not found")

    dataset = await db.get(Dataset, scene.dataset_id)
    taxonomy = dataset.taxonomy if dataset else {}

    annotation_mode: str | None = None
    if taxonomy_id is not None:
        tax_obj = await db.get(Taxonomy, taxonomy_id)
        if tax_obj:
            annotation_mode = tax_obj.annotation_mode

    scene_classes = await get_segmentation_taxonomy_classes(db, scene.dataset_id)

    stmt = select(Task).where(Task.scene_id == scene_id)
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())

    all_annotations: dict[str, list[dict[str, Any]]] = {
        "cuboids_3d": [],
        "boxes_2d": [],
        "annotations_4d": [],
        "annotations_fusion": [],
        "annotations_legacy": [],
        "tracks_2d": [],
    }

    task_info = []
    task_annotations_by_id: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for task in tasks:
        task_annotations = await get_annotations_for_task(
            db, task.id, taxonomy_id=taxonomy_id, annotation_mode=annotation_mode
        )
        task_annotations_by_id[str(task.id)] = task_annotations
        for key in all_annotations:
            all_annotations[key].extend(task_annotations[key])
        task_info.append({
            "id": str(task.id),
            "name": task.name,
            "status": task.status,
            "stage": task.stage,
            "taxonomy_id": str(task.taxonomy_id) if task.taxonomy_id else None,
            "frame_range": {
                "start": task.frame_range.lower if task.frame_range else 0,
                "end": (task.frame_range.upper - 1) if task.frame_range else 0,
            },
        })

    all_annotations = merge_overlapping_annotations(all_annotations)
    frames_data = await get_frames_metadata(db, scene.id)

    metadata: dict[str, Any] = {
        "export_info": {
            "format_version": "2.0",
            "format": format,
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": username,
            "export_type": "scene",
            "taxonomy_id": str(taxonomy_id) if taxonomy_id else None,
            "annotation_mode": annotation_mode,
        },
        "scene": get_scene_metadata(scene),
        "dataset": {
            "id": str(dataset.id) if dataset else None,
            "name": dataset.name if dataset else None,
        },
        "taxonomy": taxonomy,
        "tasks": task_info,
        "frames": frames_data,
    }

    if format == "coco":
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if annotation_mode != "segmentation_3d":
                if len(tasks) > 1:
                    metadata["export_info"]["format_version"] = "3.0"
                    metadata["export_info"]["annotation_layout"] = "per_task_sensor_files"

                    task_exports = []
                    counts_by_task: dict[str, dict[str, int]] = {}
                    aggregate_counts: dict[str, int] = defaultdict(int)

                    for task in tasks:
                        task_id_str = str(task.id)
                        task_folder = build_task_export_folder_name(task)
                        task_prefix = f"annotations/tasks/{task_folder}"

                        task_counts = add_sensor_annotations_to_zip(
                            zf,
                            task_annotations_by_id.get(task_id_str, {}),
                            frames_data,
                            taxonomy,
                            scene,
                            prefix=task_prefix,
                        )
                        counts_by_task[task_id_str] = task_counts
                        for sensor_name, count in task_counts.items():
                            aggregate_counts[sensor_name] += count

                        task_exports.append({
                            "task_id": task_id_str,
                            "task_name": task.name,
                            "task_taxonomy_id": str(task.taxonomy_id) if task.taxonomy_id else None,
                            "frame_range": {
                                "start": task.frame_range.lower if task.frame_range else 0,
                                "end": (task.frame_range.upper - 1) if task.frame_range else 0,
                            },
                            "folder": task_prefix,
                        })

                    metadata["task_exports"] = task_exports
                    metadata["annotation_counts_by_task"] = counts_by_task
                    metadata["annotation_counts"] = dict(aggregate_counts)
                else:
                    annotation_counts = add_sensor_annotations_to_zip(
                        zf, all_annotations, frames_data, taxonomy, scene, prefix="annotations"
                    )
                    metadata["annotation_counts"] = annotation_counts

            if include_data:
                add_scene_data_to_zip(zf, scene, frames_data, prefix="data")

            if taxonomy_id is None or annotation_mode == "segmentation_3d":
                add_segmentation_kitti_to_zip(
                    zf,
                    scene,
                    frames_data,
                    taxonomy,
                    prefix="annotations",
                    scene_classes=scene_classes,
                )

            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

        zip_buffer.seek(0)
        filename = (
            f"scene_{scene.name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        )
        return zip_buffer, "application/zip", filename
    else:
        export_data = {
            **metadata,
            "annotations": all_annotations,
            "annotation_counts": {
                "cuboids_3d": len(all_annotations["cuboids_3d"]),
                "boxes_2d": len(all_annotations["boxes_2d"]),
                "annotations_4d": len(all_annotations["annotations_4d"]),
                "annotations_fusion": len(all_annotations["annotations_fusion"]),
                "total": sum(len(v) for v in all_annotations.values()),
            },
        }

        if include_data:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("labels.json", json.dumps(export_data, indent=2))
                add_scene_data_to_zip(zf, scene, frames_data, prefix="data")

            zip_buffer.seek(0)
            filename = (
                f"scene_{scene.name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
            )
            return zip_buffer, "application/zip", filename
        else:
            filename = (
                f"scene_{scene.name}_labels_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
            )
            buffer = io.BytesIO(json.dumps(export_data, indent=2).encode())
            return buffer, "application/json", filename


async def export_dataset_bundle(
    db: AsyncSession,
    *,
    dataset_id: UUID,
    include_data: bool = False,
    accepted_only: bool = False,
    format: Literal["json", "coco"] = "coco",
    username: str,
) -> tuple[io.BytesIO, str, str]:
    """Build dataset export bundle across all scenes and tasks."""
    dataset = await db.get(Dataset, dataset_id)
    if not dataset:
        raise ExportNotFoundError("Dataset not found")

    taxonomy = dataset.taxonomy or {}

    stmt = select(Scene).where(Scene.dataset_id == dataset_id)
    result = await db.execute(stmt)
    scenes = list(result.scalars().all())

    scenes_data = []
    total_annotations: dict[str, int] = {
        "cuboids_3d": 0,
        "boxes_2d": 0,
        "annotations_4d": 0,
        "annotations_fusion": 0,
        "annotations_legacy": 0,
        "tracks_2d": 0,
    }

    for scene in scenes:
        task_query = select(Task).where(Task.scene_id == scene.id)
        if accepted_only:
            task_query = task_query.where(Task.status == "accepted")
        result = await db.execute(task_query)
        tasks = list(result.scalars().all())

        scene_annotations: dict[str, list[dict[str, Any]]] = {
            "cuboids_3d": [],
            "boxes_2d": [],
            "annotations_4d": [],
            "annotations_fusion": [],
            "annotations_legacy": [],
            "tracks_2d": [],
        }

        for task in tasks:
            task_annotations = await get_annotations_for_task(db, task.id)
            for key in scene_annotations:
                scene_annotations[key].extend(task_annotations[key])
                total_annotations[key] += len(task_annotations[key])

        scene_annotations = merge_overlapping_annotations(scene_annotations)

        scenes_data.append({
            "scene": scene,
            "scene_metadata": get_scene_metadata(scene),
            "frames": await get_frames_metadata(db, scene.id),
            "task_count": len(tasks),
            "annotations": scene_annotations,
        })

    metadata: dict[str, Any] = {
        "export_info": {
            "format_version": "2.0",
            "format": format,
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": username,
            "export_type": "dataset",
            "accepted_only": accepted_only,
        },
        "dataset": {
            "id": str(dataset.id),
            "name": dataset.name,
            "description": dataset.description,
            "sensor_config": dataset.sensor_config,
        },
        "taxonomy": taxonomy,
        "summary": {
            "scene_count": len(scenes),
            "total_annotations": total_annotations,
            "total_annotation_count": sum(total_annotations.values()),
        },
    }

    if format == "coco":
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            all_scene_counts: dict[str, dict[str, int]] = {}
            for scene_data in scenes_data:
                scene = scene_data["scene"]
                scene_name = scene.name.replace("/", "_").replace("\\", "_")

                scene_metadata = {
                    "scene": scene_data["scene_metadata"],
                    "frames": scene_data["frames"],
                    "task_count": scene_data["task_count"],
                }
                zf.writestr(f"{scene_name}/metadata.json", json.dumps(scene_metadata, indent=2))

                annotation_counts = add_sensor_annotations_to_zip(
                    zf,
                    scene_data["annotations"],
                    scene_data["frames"],
                    taxonomy,
                    scene,
                    prefix=f"{scene_name}/annotations",
                )
                all_scene_counts[scene_name] = annotation_counts

                if include_data:
                    add_scene_data_to_zip(
                        zf, scene, scene_data["frames"], prefix=f"{scene_name}/data"
                    )

                sc_classes = await get_segmentation_taxonomy_classes(db, scene.dataset_id)
                add_segmentation_kitti_to_zip(
                    zf,
                    scene,
                    scene_data["frames"],
                    taxonomy,
                    prefix=f"{scene_name}/annotations",
                    scene_classes=sc_classes,
                )

            metadata["scene_annotation_counts"] = all_scene_counts
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

        zip_buffer.seek(0)
        filename = (
            f"dataset_{dataset.name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        )
        return zip_buffer, "application/zip", filename
    else:
        export_data = {
            **metadata,
            "scenes": [
                {
                    "scene": sd["scene_metadata"],
                    "frames": sd["frames"],
                    "task_count": sd["task_count"],
                    "annotations": sd["annotations"],
                }
                for sd in scenes_data
            ],
        }

        if include_data:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("labels.json", json.dumps(export_data, indent=2))

                for scene_data in scenes_data:
                    scene = scene_data["scene"]
                    scene_prefix = f"data/{scene.name}"
                    add_scene_data_to_zip(
                        zf, scene, scene_data["frames"], prefix=scene_prefix
                    )

            zip_buffer.seek(0)
            filename = (
                f"dataset_{dataset.name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
            )
            return zip_buffer, "application/zip", filename
        else:
            filename = (
                f"dataset_{dataset.name}_labels_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
            )
            buffer = io.BytesIO(json.dumps(export_data, indent=2).encode())
            return buffer, "application/json", filename
