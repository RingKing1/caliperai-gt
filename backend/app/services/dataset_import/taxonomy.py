"""Taxonomy derivation/merging and class mapping during import."""
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Campaign,
    Dataset,
    Scene,
    Task,
    Taxonomy,
    TaxonomyAnnotationMode,
    dataset_taxonomy_association,
)
from app.services.dataset_import.constants import AUTO_CLASS_COLORS

logger = logging.getLogger(__name__)


def scan_annotations_for_classes(scene_dirs: list[Path]) -> set:
    """
    Scan annotation files across all scene directories to extract unique class labels.

    Supports:
    - KITTI format 3D annotations (annotations/lidar/*.txt or label_2/*.txt)
    - COCO format 2D annotations (annotations/*.json)

    Args:
        scene_dirs: List of scene directory paths to scan

    Returns:
        Set of unique class labels found in annotations
    """
    classes = set()

    for scene_dir in scene_dirs:
        annotations_dir = scene_dir / "annotations"

        if not annotations_dir.exists():
            parent_annotations_dir = scene_dir.parent / "annotations"
            if parent_annotations_dir.exists():
                annotations_dir = parent_annotations_dir

        label_2_dir = scene_dir / "label_2"
        if label_2_dir.exists():
            for txt_file in label_2_dir.glob("*.txt"):
                try:
                    with open(txt_file, "r") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 1:
                                class_label = parts[0]
                                if class_label.lower() != "dontcare":
                                    classes.add(class_label)
                except Exception:
                    continue

        if not annotations_dir.exists():
            continue

        lidar_annotations_dir = annotations_dir / "lidar"
        if not lidar_annotations_dir.exists():
            lidar_annotations_dir = annotations_dir / "label_2"
        if lidar_annotations_dir.exists():
            for txt_file in lidar_annotations_dir.glob("*.txt"):
                try:
                    with open(txt_file, "r") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 1:
                                if len(parts) >= 17 and parts[0].isdigit() and parts[1].isdigit():
                                    class_label = parts[2]
                                else:
                                    class_label = parts[0]
                                if class_label.lower() not in ("dontcare", "dont_care"):
                                    classes.add(class_label)
                except Exception:
                    continue

        for json_file in annotations_dir.glob("*.json"):
            if json_file.name == "metadata.json":
                continue
            try:
                with open(json_file, "r") as f:
                    coco_data = json.load(f)

                for cat in coco_data.get("categories", []):
                    class_name = cat.get("name")
                    if class_name:
                        classes.add(class_name)
            except Exception:
                continue

    logger.info(f"[DERIVE TAXONOMY] Found {len(classes)} unique classes: {classes}")
    return classes


async def derive_and_merge_taxonomy(
    db: AsyncSession,
    dataset: Dataset,
    discovered_classes: set,
    user_id: UUID,
) -> Taxonomy | None:
    """
    Create or merge taxonomy based on discovered classes from annotations.

    If dataset has no taxonomy:
        - Create a new taxonomy with all discovered classes
        - Link it to the dataset

    If dataset has existing taxonomy:
        - Add any missing classes to the existing taxonomy (merge)

    Args:
        db: Database session
        dataset: The dataset to link taxonomy to
        discovered_classes: Set of class labels found in annotations
        user_id: ID of user performing the import

    Returns:
        The created or updated Taxonomy, or None if no classes discovered
    """
    if not discovered_classes:
        logger.info(f"[DERIVE TAXONOMY] No classes discovered, skipping taxonomy creation")
        return None

    taxonomy_result = await db.execute(
        select(Taxonomy)
        .join(dataset_taxonomy_association)
        .where(dataset_taxonomy_association.c.dataset_id == dataset.id)
        .where(Taxonomy.is_deleted == False)
    )
    existing_taxonomies = list(taxonomy_result.scalars().all())

    if existing_taxonomies:
        taxonomy = existing_taxonomies[0]
        existing_class_ids = {cls.get("id", "").lower() for cls in (taxonomy.classes or [])}
        existing_class_names = {cls.get("name", "").lower() for cls in (taxonomy.classes or [])}

        new_classes = []
        color_idx = len(taxonomy.classes or [])

        for class_label in sorted(discovered_classes):
            if class_label.lower() not in existing_class_ids and class_label.lower() not in existing_class_names:
                new_classes.append({
                    "id": class_label,
                    "name": class_label,
                    "color": AUTO_CLASS_COLORS[color_idx % len(AUTO_CLASS_COLORS)],
                    "type": ["cuboid", "box2d"],
                    "attributes": {},
                })
                color_idx += 1

        if new_classes:
            updated_classes = list(taxonomy.classes or []) + new_classes
            taxonomy.classes = updated_classes
            await db.flush()
            logger.info(f"[DERIVE TAXONOMY] Merged {len(new_classes)} new classes into existing taxonomy '{taxonomy.name}'")
            logger.info(f"[DERIVE TAXONOMY] New classes: {[c['name'] for c in new_classes]}")
        else:
            logger.info(f"[DERIVE TAXONOMY] All discovered classes already exist in taxonomy '{taxonomy.name}'")

        return taxonomy

    else:
        taxonomy_classes = []
        for idx, class_label in enumerate(sorted(discovered_classes)):
            taxonomy_classes.append({
                "id": class_label,
                "name": class_label,
                "color": AUTO_CLASS_COLORS[idx % len(AUTO_CLASS_COLORS)],
                "type": ["cuboid", "box2d"],
                "attributes": {},
            })

        taxonomy = Taxonomy(
            organization_id=dataset.campaign.organization_id,
            name=f"Auto-derived from {dataset.name}",
            description=f"Taxonomy automatically derived from imported annotations for dataset '{dataset.name}'",
            classes=taxonomy_classes,
            is_deleted=False,
        )
        db.add(taxonomy)
        await db.flush()

        await db.execute(
            dataset_taxonomy_association.insert().values(
                dataset_id=dataset.id,
                taxonomy_id=taxonomy.id,
            )
        )
        await db.flush()

        logger.info(f"[DERIVE TAXONOMY] Created new taxonomy '{taxonomy.name}' with {len(taxonomy_classes)} classes")
        logger.info(f"[DERIVE TAXONOMY] Classes: {[c['name'] for c in taxonomy_classes]}")

        return taxonomy


def _read_segmentation_class_order(annotations_dir: Path) -> list[str]:
    """Return segmentation class names ordered so index i == stored label i.

    Reads the exported ``labels_info.json`` (sibling of the ``*.label`` files).
    Its ``class_distribution`` is keyed by 1-based KITTI-semantic id (1=first
    class); imported labels are stored 0-based (id-1). So class id ``k`` maps to
    taxonomy index ``k-1``. Missing ids are filled with placeholders so the
    positional mapping stays intact.
    """
    info_files = list(annotations_dir.rglob("labels_info.json"))
    if not info_files:
        return []
    try:
        info = json.loads(info_files[0].read_text())
    except Exception:
        return []

    id_to_name: dict[int, str] = {}
    for frame in info.get("frames", []):
        for sid, meta in (frame.get("class_distribution") or {}).items():
            try:
                cid = int(sid)
            except (TypeError, ValueError):
                continue
            name = (meta or {}).get("name") if isinstance(meta, dict) else None
            if cid >= 1 and name and cid not in id_to_name:
                id_to_name[cid] = name
    if not id_to_name:
        return []

    max_id = max(id_to_name)
    return [id_to_name.get(i, f"class_{i}") for i in range(1, max_id + 1)]


async def ensure_segmentation_taxonomy(
    db: AsyncSession,
    scene: Scene,
    ordered_class_names: list[str],
) -> Taxonomy | None:
    """Ensure the scene's dataset has a ``segmentation_3d`` taxonomy whose class
    ORDER matches the stored 0-based per-point labels (index 0 = first class).

    The 3D segmentation editor colors points by the 0-based position of each
    class in a ``segmentation_3d`` taxonomy (``classColors.set(index, color)``).
    Without a matching taxonomy the imported labels load but render colorless, so
    we derive one from the export's class order. No-ops if the dataset already
    has a ``segmentation_3d`` taxonomy.
    """
    if not ordered_class_names:
        return None

    existing = await db.execute(
        select(Taxonomy)
        .join(dataset_taxonomy_association)
        .where(dataset_taxonomy_association.c.dataset_id == scene.dataset_id)
        .where(Taxonomy.annotation_mode == "segmentation_3d")
        .where(Taxonomy.is_deleted == False)
    )
    existing_tax = existing.scalars().first()
    if existing_tax:
        return existing_tax

    dataset = (await db.execute(
        select(Dataset).where(Dataset.id == scene.dataset_id)
    )).scalar_one_or_none()
    if not dataset:
        return None
    campaign = (await db.execute(
        select(Campaign).where(Campaign.id == dataset.campaign_id)
    )).scalar_one_or_none()
    if not campaign:
        return None

    classes = [
        {
            "id": name,
            "name": name.replace("_", " ").title(),
            "color": AUTO_CLASS_COLORS[idx % len(AUTO_CLASS_COLORS)],
            "type": ["segmentation_3d"],
            "attributes": {},
        }
        for idx, name in enumerate(ordered_class_names)
    ]

    # Avoid duplicate taxonomies: if the organization already has a
    # segmentation_3d taxonomy with the identical, identically-ordered class set,
    # reuse it (link it to this dataset) instead of minting a new one. The class
    # ORDER must match exactly because per-point labels are stored as 0-based
    # indices into the class list.
    signature = [c["id"] for c in classes]
    org_taxes = await db.execute(
        select(Taxonomy).where(
            Taxonomy.organization_id == campaign.organization_id,
            Taxonomy.annotation_mode == "segmentation_3d",
            Taxonomy.is_deleted == False,
        )
    )
    for cand in org_taxes.scalars().all():
        if [c.get("id") for c in (cand.classes or [])] == signature:
            await db.execute(
                dataset_taxonomy_association.insert().values(
                    dataset_id=scene.dataset_id,
                    taxonomy_id=cand.id,
                    mode="segmentation_3d",
                    is_primary=True,
                )
            )
            await db.flush()
            logger.info(f"[IMPORT] Reused existing segmentation_3d taxonomy '{cand.name}' ({cand.id})")
            return cand

    taxonomy = Taxonomy(
        organization_id=campaign.organization_id,
        name=f"{dataset.name} — 3D Segmentation",
        description="Derived from imported 3D segmentation labels (labels_info.json).",
        annotation_mode="segmentation_3d",
        classes=classes,
        is_deleted=False,
    )
    db.add(taxonomy)
    await db.flush()
    await db.execute(
        dataset_taxonomy_association.insert().values(
            dataset_id=scene.dataset_id,
            taxonomy_id=taxonomy.id,
            mode="segmentation_3d",
            is_primary=True,
        )
    )
    await db.flush()
    logger.info(f"[IMPORT] Created segmentation_3d taxonomy with {len(classes)} classes: {[c['name'] for c in classes]}")
    return taxonomy


def build_class_mapping(taxonomy_classes: list) -> dict:
    """
    Build a mapping from various class name formats to taxonomy class IDs.
    Handles case-insensitive matching and common naming variations.

    Args:
        taxonomy_classes: List of taxonomy class dicts with 'id' and 'name' keys

    Returns:
        Dict mapping lowercase class names/variations to taxonomy class IDs
    """
    mapping = {}

    for cls in taxonomy_classes:
        class_id = cls.get("id", "")
        class_name = cls.get("name", "")

        if not class_id:
            continue

        mapping[class_id.lower()] = class_id

        if class_name:
            mapping[class_name.lower()] = class_id

        name_lower = class_name.lower()
        id_lower = class_id.lower()

        mapping[name_lower.replace("_", " ")] = class_id
        mapping[name_lower.replace(" ", "_")] = class_id
        mapping[id_lower.replace("_", " ")] = class_id
        mapping[id_lower.replace(" ", "_")] = class_id

        mapping[name_lower.replace("-", "_")] = class_id
        mapping[name_lower.replace("-", " ")] = class_id

        if "_" in id_lower:
            last_part = id_lower.split("_")[-1]
            if last_part not in mapping:
                mapping[last_part] = class_id

        if "_" in name_lower:
            last_part = name_lower.split("_")[-1]
            if last_part not in mapping:
                mapping[last_part] = class_id

    return mapping


def map_class_to_taxonomy(class_label: str, class_mapping: dict) -> str:
    """
    Map an imported class label to a taxonomy class ID.

    Args:
        class_label: The class label from imported annotations
        class_mapping: Dict from build_class_mapping()

    Returns:
        Mapped taxonomy class ID, or original label if no match found
    """
    label_lower = class_label.lower().strip()

    if label_lower in class_mapping:
        return class_mapping[label_lower]

    if label_lower.replace("_", " ") in class_mapping:
        return class_mapping[label_lower.replace("_", " ")]
    if label_lower.replace(" ", "_") in class_mapping:
        return class_mapping[label_lower.replace(" ", "_")]

    if label_lower.replace("-", "_") in class_mapping:
        return class_mapping[label_lower.replace("-", "_")]

    logger.warning(f"[IMPORT] Warning: Class '{class_label}' not found in taxonomy, using as-is")
    return class_label



# ---------------------------------------------------------------------------
# Annotation-import taxonomy helpers (COCO/KITTI class derivation)
# ---------------------------------------------------------------------------
def generate_random_color() -> str:
    """Generate a random hex color."""
    return f"#{random.randint(0, 255):02x}{random.randint(0, 255):02x}{random.randint(0, 255):02x}"


def map_source_class_to_taxonomy(source_class_name: str, taxonomy: dict[str, Any]) -> str:
    """Map a source annotation class name to a taxonomy class ID.

    This function handles the mismatch between class names in imported files
    (e.g., "Car", "Truck", "bi_cycle") and taxonomy class IDs/names.

    Only does EXACT matching (case-insensitive). If no exact match is found,
    returns the normalized source name so it can be added to taxonomy later.

    Args:
        source_class_name: Class name from the source file (KITTI, COCO, etc.)
        taxonomy: Dataset taxonomy dict with "classes" list

    Returns:
        The matching taxonomy class ID, or the normalized source name if no match found
    """
    if not taxonomy or "classes" not in taxonomy:
        return source_class_name.lower().replace(" ", "_").replace("-", "_")

    normalized_source = source_class_name.lower().replace(" ", "_").replace("-", "_")

    for cls in taxonomy["classes"]:
        cls_id = cls.get("id", "")
        cls_name = cls.get("name", "")

        if cls_id.lower() == normalized_source:
            return cls_id

        if cls_name.lower().replace(" ", "_").replace("-", "_") == normalized_source:
            return cls_id

    return normalized_source


async def create_taxonomy_from_classes(
    db: AsyncSession,
    task: Task,
    class_ids: set[str],
    annotation_mode: str = TaxonomyAnnotationMode.FUSION_3D.value,
    coco_categories: dict[int, dict[str, Any]] | None = None
) -> None:
    """Create or update taxonomy at the dataset level based on imported annotation classes.

    This function now supports annotation modes:
    - fusion_3d: Classes get cuboid, box2d, polygon types (for 3D/fusion annotations)
    - 2d_only: Classes get box2d, polygon, polyline types (for pure 2D annotations)

    Args:
        db: Database session
        task: Task whose dataset will receive the taxonomy
        class_ids: Set of unique class IDs found in annotations
        annotation_mode: "fusion_3d" or "2d_only" - determines annotation types for classes
        coco_categories: Optional COCO categories dict with id -> {name, supercategory}
    """
    if not class_ids:
        return

    try:
        scene_result = await db.execute(
            select(Scene).where(Scene.id == task.scene_id)
        )
        scene = scene_result.scalar_one_or_none()

        if not scene:
            logger.warning(f"Scene not found for task {task.id}")
            return

        dataset_result = await db.execute(
            select(Dataset).where(Dataset.id == scene.dataset_id)
        )
        dataset = dataset_result.scalar_one_or_none()

        if not dataset:
            logger.warning(f"Dataset not found for scene {scene.id}")
            return

        existing_taxonomy = dataset.taxonomy or {}
        existing_classes = {cls.get("id"): cls for cls in existing_taxonomy.get("classes", [])}

        updated = False
        for class_id in sorted(class_ids):
            if class_id not in existing_classes:
                class_name = class_id

                if coco_categories:
                    try:
                        coco_id = int(class_id)
                        if coco_id in coco_categories:
                            class_name = coco_categories[coco_id].get("name", class_id)
                    except (ValueError, KeyError):
                        pass

                if annotation_mode == TaxonomyAnnotationMode.FUSION_3D.value:
                    class_types = ["cuboid", "box2d", "polygon"]
                else:
                    class_types = ["box2d", "polygon", "polyline", "keypoints"]

                new_class = {
                    "id": class_id,
                    "name": class_name,
                    "color": generate_random_color(),
                    "type": class_types
                }

                if "classes" not in existing_taxonomy:
                    existing_taxonomy["classes"] = []

                existing_taxonomy["classes"].append(new_class)
                existing_classes[class_id] = new_class
                updated = True
                logger.info(f"Added class '{class_id}' to dataset taxonomy (mode: {annotation_mode})")

        if updated:
            if "attributes" not in existing_taxonomy:
                existing_taxonomy["attributes"] = []
            if "annotation_rules" not in existing_taxonomy:
                existing_taxonomy["annotation_rules"] = {}

            dataset.taxonomy = existing_taxonomy
            await db.commit()
            logger.info(f"Updated dataset {dataset.id} taxonomy with {len(class_ids)} classes (mode: {annotation_mode})")
        else:
            logger.info(f"All {len(class_ids)} classes already exist in dataset taxonomy")

    except Exception as e:
        logger.error(f"Error creating taxonomy: {e}", exc_info=True)
        pass


async def derive_and_merge_taxonomy_for_scene(
    db: AsyncSession,
    dataset: Dataset,
    unique_class_ids: set[str],
    coco_categories: dict[int, dict] | None = None,
    class_ids_by_mode: dict[str, set[str]] | None = None
) -> list[str]:
    """
    Derive classes from annotations and merge into dataset's taxonomy.

    Returns list of newly added class names.
    """
    if not unique_class_ids:
        return []

    existing_taxonomy = dataset.taxonomy or {}

    existing_class_ids = set()
    existing_class_names = set()
    for c in existing_taxonomy.get("classes", []):
        cls_id = c.get("id", "")
        cls_name = c.get("name", "")
        if cls_id:
            existing_class_ids.add(cls_id.lower())
        if cls_name:
            existing_class_names.add(cls_name.lower())

    existing_classes = {c.get("name", c.get("id", "")): c for c in existing_taxonomy.get("classes", [])}

    fusion_3d_classes = class_ids_by_mode.get(TaxonomyAnnotationMode.FUSION_3D.value, set()) if class_ids_by_mode else set()
    only_2d_classes = class_ids_by_mode.get(TaxonomyAnnotationMode.ONLY_2D.value, set()) if class_ids_by_mode else set()

    used_colors = {c.get("color") for c in existing_classes.values() if c.get("color")}
    available_colors = [c for c in CLASS_COLOR_PALETTE if c not in used_colors]
    color_idx = 0

    new_classes = []
    for class_id in unique_class_ids:
        class_name = str(class_id)
        class_name_lower = class_name.lower()

        if class_name_lower in existing_class_ids or class_name_lower in existing_class_names:
            continue

        types = []
        if class_name in fusion_3d_classes:
            types.append("cuboid")
        if class_name in only_2d_classes:
            types.append("box2d")
        if not types:
            types = ["cuboid", "box2d"]

        color = None
        if coco_categories:
            for cat in coco_categories.values():
                if cat.get("name") == class_name:
                    color = cat.get("color")
                    break

        if not color:
            if color_idx < len(available_colors):
                color = available_colors[color_idx]
                color_idx += 1
            else:
                color = f"#{random.randint(0, 0xFFFFFF):06x}"

        display_name = class_name.replace("_", " ").title()

        new_class = {
            "id": class_name,
            "name": display_name,
            "color": color,
            "type": types,
            "attributes": {}
        }
        new_classes.append(new_class)

    if not new_classes:
        return []

    updated_taxonomy = existing_taxonomy.copy()
    if "classes" not in updated_taxonomy:
        updated_taxonomy["classes"] = []
    updated_taxonomy["classes"].extend(new_classes)

    dataset.taxonomy = updated_taxonomy
    await db.commit()

    return [c["name"] for c in new_classes]



CLASS_COLOR_PALETTE = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
    '#F1948A', '#82E0AA', '#F8C471', '#D7BDE2', '#A9CCE3',
    '#FAD7A0', '#A3E4D7', '#D5A6BD', '#AED6F1', '#F5B7B1',
]


def derive_taxonomy_from_annotations(
    annotation_files: dict[str, dict],
    dataset_name: str
) -> dict[str, Any]:
    """
    Derive a taxonomy from annotation files by extracting unique classes.

    Args:
        annotation_files: Dict mapping sensor_name to COCO-format annotation data
        dataset_name: Name of the dataset for taxonomy naming

    Returns:
        Taxonomy dict with classes, skeletons, and annotation_rules
    """
    classes_found = {}

    for sensor_name, coco_data in annotation_files.items():
        is_3d = sensor_name.lower() in ['lidar', 'velodyne', 'point_cloud', 'pointcloud']

        for cat in coco_data.get("categories", []):
            cat_name = cat.get("name", f"class_{cat.get('id', 0)}")
            if cat_name not in classes_found:
                classes_found[cat_name] = {"types": set(), "count": 0}

            if is_3d:
                classes_found[cat_name]["types"].add("cuboid")
            else:
                classes_found[cat_name]["types"].add("box2d")

        category_map = {cat["id"]: cat.get("name", f"class_{cat['id']}") for cat in coco_data.get("categories", [])}
        for ann in coco_data.get("annotations", []):
            cat_id = ann.get("category_id")
            if cat_id in category_map:
                class_name = category_map[cat_id]
                if class_name in classes_found:
                    classes_found[class_name]["count"] += 1

                    if "bbox3d" in ann or "dimensions" in ann:
                        classes_found[class_name]["types"].add("cuboid")
                    if "segmentation" in ann and isinstance(ann["segmentation"], list):
                        if any(isinstance(seg, list) for seg in ann["segmentation"]):
                            classes_found[class_name]["types"].add("polygon")
                    if "keypoints" in ann:
                        classes_found[class_name]["types"].add("skeleton")

    taxonomy_classes = []
    for idx, (class_name, info) in enumerate(sorted(classes_found.items())):
        class_id = class_name.lower().replace(" ", "_").replace("-", "_")
        color = CLASS_COLOR_PALETTE[idx % len(CLASS_COLOR_PALETTE)]
        types = list(info["types"]) if info["types"] else ["box2d", "cuboid"]

        taxonomy_classes.append({
            "id": class_id,
            "name": class_name,
            "color": color,
            "type": types,
            "attributes": {},
        })

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    taxonomy_name = f"{dataset_name}_imported_{timestamp}"

    return {
        "name": taxonomy_name,
        "classes": taxonomy_classes,
        "skeletons": {},
        "annotation_rules": {
            "min_points_polyline": 2,
            "min_points_polygon": 3,
            "allow_overlapping_boxes": False,
            "require_track_id": True,
        },
    }

