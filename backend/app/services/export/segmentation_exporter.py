"""3D Semantic Segmentation KITTI-format export module."""
from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Taxonomy, dataset_taxonomy_association

if TYPE_CHECKING:
    from app.models.models import Scene

SEGMENTATION_ROOT = os.environ.get("SEGMENTATION_ROOT", "/uploads/segmentation")


async def get_segmentation_taxonomy_classes(
    db: AsyncSession, dataset_id: UUID
) -> list[dict[str, Any]] | None:
    """Return the classes list of the segmentation_3d taxonomy linked to this dataset,

    or None if no such taxonomy is linked.
    """
    stmt = (
        select(Taxonomy)
        .join(
            dataset_taxonomy_association,
            Taxonomy.id == dataset_taxonomy_association.c.taxonomy_id,
        )
        .where(
            dataset_taxonomy_association.c.dataset_id == dataset_id,
            dataset_taxonomy_association.c.mode == "segmentation_3d",
            Taxonomy.is_deleted.is_(False),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    tax = result.scalar_one_or_none()
    return list(tax.classes) if tax and tax.classes else None


def add_segmentation_kitti_to_zip(
    zf: zipfile.ZipFile,
    scene: Scene,
    frames_data: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    prefix: str = "annotations",
    scene_classes: list[dict[str, Any]] | None = None,
) -> int:
    """Add 3D semantic segmentation .label files under {prefix}/lidar_segmentation/.

    Structure mirrors lidar.json exactly — same info/frames/categories shape:

        {prefix}/lidar_segmentation/
            labels_info.json   ← info + frames + categories  (same structure as lidar.json)
            000000.label       ← binary uint32 per point
            000001.label
            ...

    Encoding per uint32:
        bits  0-15: semantic class ID (0=unlabeled, 1=first taxonomy class, …)
        bits 16-31: instance ID       (0=no instance)
    """
    seg_root = Path(SEGMENTATION_ROOT) / str(scene.id)
    if not seg_root.exists():
        return 0

    classes = scene_classes if scene_classes is not None else taxonomy.get("classes", [])
    id_to_cat: dict[int, dict[str, Any]] = {
        0: {"id": 0, "name": "unlabeled", "color": "", "supercategory": ""}
    }
    for idx, cls in enumerate(classes):
        id_to_cat[idx + 1] = {
            "id": idx + 1,
            "name": cls.get("name", cls.get("id", f"class_{idx}")),
            "color": cls.get("color", ""),
            "supercategory": cls.get("supercategory", "object"),
        }

    frame_entries: list[dict[str, Any]] = []
    frames_exported = 0

    for frame in frames_data:
        frame_id = frame.get("id") or frame.get("frame_id")
        frame_index = frame.get("frame_index", 0)

        file_paths = frame.get("file_paths") or {}
        pcd_file = file_paths.get("lidar", "") if isinstance(file_paths, dict) else ""

        labels_path = seg_root / f"{frame_id}.npy"
        has_labels = labels_path.exists()

        entry: dict[str, Any] = {
            "id": frame_index,
            "frame_number": frame_index + 1,
            "frame_index": frame_index,
            "file_name": f"{frame_index:06d}.label",
            "pcd_file": pcd_file,
            "timestamp": frame.get("timestamp", 0.0),
            "has_labels": has_labels,
        }

        if has_labels:
            labels = np.load(str(labels_path))
            semantic_ids = np.where(labels < 0, 0, labels + 1).astype(np.uint32)

            instance_path = seg_root / f"{frame_id}_instances.npy"
            if instance_path.exists():
                instances = np.load(str(instance_path)).astype(np.uint32)
                instances = np.where(instances < 0, 0, instances)
                kitti_labels = semantic_ids | (instances << np.uint32(16))
            else:
                kitti_labels = semantic_ids

            labeled_mask = semantic_ids > 0
            entry["labeled_point_count"] = int(np.sum(labeled_mask))
            entry["total_point_count"] = int(len(labels))

            unique_ids, counts = np.unique(semantic_ids[labeled_mask], return_counts=True)
            class_dist: dict[str, dict[str, Any]] = {}
            for sem_id, count in zip(unique_ids.tolist(), counts.tolist()):
                cat = id_to_cat.get(sem_id)
                cat_name = cat["name"] if cat else f"class_{sem_id}"
                class_dist[str(sem_id)] = {"name": cat_name, "point_count": count}
                if sem_id not in id_to_cat:
                    id_to_cat[sem_id] = {
                        "id": sem_id,
                        "name": f"class_{sem_id}",
                        "color": "",
                        "supercategory": "object",
                    }
            entry["class_distribution"] = class_dist

            zf.writestr(
                f"{prefix}/lidar_segmentation/{frame_index:06d}.label",
                kitti_labels.tobytes(),
            )
            frames_exported += 1

        semantic_path = seg_root / f"{frame_id}_semantic.npy"
        if semantic_path.exists():
            sem = np.load(str(semantic_path))
            sem_kitti = np.where(sem < 0, 0, sem + 1).astype(np.uint32)
            zf.writestr(
                f"{prefix}/lidar_segmentation_semantic/{frame_index:06d}.label",
                sem_kitti.tobytes(),
            )
            entry["has_semantic"] = True

        frame_entries.append(entry)

    if frames_exported == 0:
        return 0

    categories = [id_to_cat[k] for k in sorted(id_to_cat.keys())]

    labels_info: dict[str, Any] = {
        "info": {
            "description": "3D Semantic Segmentation — KITTI Semantic format",
            "format": "kitti_semantic",
            "encoding": (
                "uint32 per point: "
                "semantic_id = bits 0-15 (0=unlabeled, 1=first class, ...), "
                "instance_id = bits 16-31 (0=no instance)"
            ),
            "version": "1.0",
            "year": datetime.now(UTC).year,
            "contributor": "CheryGT Export",
            "date_created": datetime.now(UTC).isoformat(),
            "scene_id": str(scene.id),
            "scene_name": scene.name,
            "coordinate_system": "lidar",
        },
        "frames": frame_entries,
        "categories": categories,
    }
    zf.writestr(
        f"{prefix}/lidar_segmentation/labels_info.json",
        json.dumps(labels_info, indent=2),
    )
    return frames_exported
