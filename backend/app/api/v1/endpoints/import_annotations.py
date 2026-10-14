"""
Annotation Import endpoints - Import annotations from external formats (COCO, KITTI, ZIP).

Supports:
- Single file imports (COCO JSON, KITTI TXT)
- ZIP file imports with per-sensor annotation files

Expected ZIP structure for multi-sensor import:
    annotations.zip/
    ├── annotations/
    │   ├── lidar.json          # COCO-like 3D annotations
    │   ├── camera_front.json   # COCO 2D annotations for camera_front
    │   ├── camera_rear.json    # COCO 2D annotations for camera_rear
    │   └── ...
    └── metadata.json (optional)

Parsing, fingerprinting and the ZIP annotation pipeline live in
``app.services.dataset_import``; this module keeps only the thin route handlers
with their original transaction boundaries.
"""
import io
import json
import zipfile
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import (
    Annotation2D,
    Annotation3D,
    AnnotationSource,
    Dataset,
    Frame,
    Permission,
    Scene,
    Task,
    Taxonomy,
    Track2D,
    User,
    dataset_taxonomy_association,
)
from app.services.dataset_import import (
    build_empty_import_results,
    build_subzip_for_task_folder,
    derive_and_merge_taxonomy_for_scene,
    derive_taxonomy_from_annotations,
    merge_import_results,
    parse_coco_2d_annotations,
    parse_coco_3d_annotations,
    process_zip_annotations,
)
from app.services.rbac_service import RequirePermissions

router = APIRouter()

@router.post("/scenes/{scene_id}/import-annotations")
async def import_annotations(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="ZIP file containing annotations folder with COCO JSON or KITTI TXT files"),
    task_id: Optional[UUID] = Form(None, description="Optional task ID to associate annotations with"),
    overwrite: bool = Form(False, description="If true, delete existing annotations before importing"),
    sync_taxonomy: bool = Form(True, description="If true, derive and merge taxonomy from annotation classes"),
):
    """
    Import annotations from a ZIP file containing the annotations folder.
    
    Requires ANNOTATIONS_CREATE permission.
    
    **Supported Folder Structures:**
    
    Format 1: All COCO
    ```
    annotations/
    ├── lidar.json              # COCO 3D (cuboids)
    ├── front_camera.json       # COCO 2D
    └── ...
    ```
    
    Format 2: KITTI LiDAR + COCO Cameras (Hybrid)
    ```
    annotations/
    ├── lidar/                  # KITTI 3D per-frame
    │   ├── 0000.txt
    │   └── ...
    ├── front_camera.json       # COCO 2D
    └── ...
    ```
    
    **Auto-detection:**
    - lidar.json → COCO 3D cuboids
    - lidar/*.txt → KITTI 3D per-frame
    - *_camera.json or other *.json → COCO 2D bboxes
    
    **Parameters:**
    - **overwrite**: If true, delete all existing annotations for this scene before importing
    - **sync_taxonomy**: If true, discover class labels and merge into dataset taxonomy
    
    Returns:
        - success: boolean
        - imported_count: number of annotations created
        - sensors_processed: dict of sensor names to counts
        - derived_classes: list of new classes added to taxonomy (if sync_taxonomy=true)
        - errors: list of errors if any
    """
    scene_query = select(Scene).where(Scene.id == scene_id, Scene.is_deleted == False)
    result = await db.execute(scene_query)
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene {scene_id} not found"
        )

    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload a ZIP file containing your annotations folder"
        )

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}"
        )

    zip_metadata: Dict[str, Any] = {}
    zip_names: List[str] = []
    embedded_task_id: Optional[str] = None
    task_exports_meta: List[Dict[str, Any]] = []
    is_per_task_layout = False
    try:
        with zipfile.ZipFile(io.BytesIO(content), 'r') as _zf:
            zip_names = _zf.namelist()
            meta_names = [n for n in zip_names if n.endswith('metadata.json') and '__MACOSX' not in n]
            if meta_names:
                zip_metadata = json.loads(_zf.read(meta_names[0]).decode('utf-8'))
                embedded_task_id = (zip_metadata.get("task") or {}).get("id")
                task_exports_meta = list(zip_metadata.get("task_exports") or [])

                export_info = zip_metadata.get("export_info") or {}
                layout = export_info.get("annotation_layout")
                if layout == "per_task_sensor_files":
                    is_per_task_layout = True

            if not is_per_task_layout:
                is_per_task_layout = any(n.startswith("annotations/tasks/") for n in zip_names)
    except Exception:
        pass

    if task_id is None and embedded_task_id and not is_per_task_layout:
        try:
            candidate = UUID(str(embedded_task_id))
            _check = await db.execute(
                select(Task).where(
                    Task.id == candidate,
                    Task.scene_id == scene_id,
                    Task.is_deleted == False,
                )
            )
            if _check.scalar_one_or_none():
                task_id = candidate
        except Exception:
            pass

    if task_id:
        task_query = select(Task).where(Task.id == task_id, Task.is_deleted == False)
        result = await db.execute(task_query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )
    else:
        task_query = select(Task).where(
            Task.scene_id == scene_id,
            Task.is_deleted == False
        ).order_by(Task.created_at.desc()).limit(1)
        result = await db.execute(task_query)
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No tasks found for scene {scene_id}. Create a task first."
            )
    
    frames_query = select(Frame).where(Frame.scene_id == scene.id).order_by(Frame.frame_index)
    frames_result = await db.execute(frames_query)
    frame_id_map = {frame.frame_index: frame.id for frame in frames_result.scalars().all()}
    
    derived_classes = []

    async def _delete_annotations_for_task(target_task_id: UUID) -> None:
        await db.execute(Annotation2D.__table__.delete().where(Annotation2D.task_id == target_task_id))
        await db.execute(Annotation3D.__table__.delete().where(Annotation3D.task_id == target_task_id))

    if is_per_task_layout and task_id is None:
        scene_tasks_result = await db.execute(
            select(Task).where(Task.scene_id == scene_id, Task.is_deleted == False)
        )
        scene_tasks = list(scene_tasks_result.scalars().all())
        scene_tasks_by_id = {str(t.id): t for t in scene_tasks}

        folder_entries: List[Dict[str, Any]] = []
        for entry in task_exports_meta:
            folder = str(entry.get("folder") or "").strip("/")
            if folder.startswith("annotations/tasks/"):
                folder_entries.append(entry)

        if not folder_entries:
            discovered = set()
            for name in zip_names:
                parts = name.strip("/").split("/")
                if len(parts) >= 3 and parts[0] == "annotations" and parts[1] == "tasks":
                    discovered.add("/".join(parts[:3]))
            folder_entries = [{"folder": f} for f in sorted(discovered)]

        if not folder_entries:
            if overwrite:
                try:
                    await _delete_annotations_for_task(task.id)
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to delete existing annotations: {str(e)}"
                    )
            zip_results = await process_zip_annotations(content, scene, task, frame_id_map, db, taxonomy_id=scene.selected_taxonomy_id)
        else:
            zip_results = build_empty_import_results()
            routed_task_ids: Set[str] = set()
            overwritten_tasks: Set[str] = set()

            for entry in folder_entries:
                folder = str(entry.get("folder") or "").strip("/")
                task_name_from_meta = (entry.get("task_name") or "").strip()
                task_taxonomy_id = entry.get("task_taxonomy_id")
                frame_range = entry.get("frame_range") or {}

                target_task: Optional[Task] = None
                explicit_task_id = entry.get("task_id")
                if explicit_task_id and str(explicit_task_id) in scene_tasks_by_id:
                    target_task = scene_tasks_by_id[str(explicit_task_id)]

                if target_task is None and task_taxonomy_id:
                    matches = [
                        t for t in scene_tasks
                        if t.taxonomy_id and str(t.taxonomy_id) == str(task_taxonomy_id)
                    ]
                    if len(matches) == 1:
                        target_task = matches[0]

                if target_task is None and frame_range:
                    try:
                        r_start = int(frame_range.get("start"))
                        r_end = int(frame_range.get("end"))
                        matches = []
                        for t in scene_tasks:
                            t_start = t.frame_range.lower if t.frame_range else 0
                            t_end = (t.frame_range.upper - 1) if t.frame_range else 0
                            if t_start == r_start and t_end == r_end:
                                matches.append(t)
                        if len(matches) == 1:
                            target_task = matches[0]
                    except Exception:
                        pass

                if target_task is None and task_name_from_meta:
                    matches = [t for t in scene_tasks if (t.name or "").strip() == task_name_from_meta]
                    if len(matches) == 1:
                        target_task = matches[0]

                if target_task is None:
                    target_task = task

                subzip = build_subzip_for_task_folder(content, folder, metadata=zip_metadata)
                if not subzip:
                    continue

                target_task_id_str = str(target_task.id)
                if overwrite and target_task_id_str not in overwritten_tasks:
                    try:
                        await _delete_annotations_for_task(target_task.id)
                        overwritten_tasks.add(target_task_id_str)
                    except Exception as e:
                        await db.rollback()
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to delete existing annotations: {str(e)}"
                        )

                per_task_results = await process_zip_annotations(
                    subzip,
                    scene,
                    target_task,
                    frame_id_map,
                    db,
                    taxonomy_id=scene.selected_taxonomy_id,
                )
                merge_import_results(
                    zip_results,
                    per_task_results,
                    sensor_prefix=f"{target_task.name} ({target_task_id_str[:8]})",
                )
                routed_task_ids.add(target_task_id_str)

            zip_results["routed_task_ids"] = sorted(routed_task_ids)
    else:
        if overwrite:
            try:
                await _delete_annotations_for_task(task.id)
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to delete existing annotations: {str(e)}"
                )

        zip_results = await process_zip_annotations(content, scene, task, frame_id_map, db, taxonomy_id=scene.selected_taxonomy_id)
    
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save annotations: {str(e)}"
        )
    
    if sync_taxonomy and zip_results["unique_class_ids"]:
        try:
            dataset_result = await db.execute(
                select(Dataset).where(Dataset.id == scene.dataset_id)
            )
            dataset = dataset_result.scalar_one_or_none()
            
            if dataset:
                derived_classes = await derive_and_merge_taxonomy_for_scene(
                    db, dataset,
                    zip_results["unique_class_ids"],
                    zip_results.get("coco_categories"),
                    zip_results.get("class_ids_by_mode", {})
                )
        except Exception as e:
            zip_results["errors"].append(f"Failed to sync taxonomy: {str(e)}")
    
    return {
        "success": True,
        "imported_count": zip_results["total_imported"],
        "task_id": str(task.id),
        "task_ids": zip_results.get("routed_task_ids", [str(task.id)]),
        "sensors_processed": zip_results["sensors_processed"],
        "derived_classes": derived_classes,
        "errors": zip_results["errors"]
    }


@router.post("/scenes/{scene_id}/import-annotations-zip")
async def import_annotations_zip(
    scene_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="ZIP file containing per-sensor annotation files"),
    task_id: Optional[UUID] = Form(None, description="Optional task ID to associate annotations with"),
    overwrite: bool = Form(False, description="If true, delete existing annotations before importing"),
    sync_taxonomy: bool = Form(True, description="If true, derive and merge taxonomy from annotation classes"),
):
    """
    Import annotations from a ZIP file. Alias for import_annotations endpoint.
    """
    return await import_annotations(
        scene_id=scene_id,
        file=file,
        task_id=task_id,
        overwrite=overwrite,
        sync_taxonomy=sync_taxonomy,
        current_user=current_user,
        db=db
    )


@router.post("/tasks/{task_id}/import-annotations")
async def import_annotations_for_task(
    task_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.ANNOTATIONS_CREATE))],
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="ZIP file containing annotations folder"),
    overwrite: bool = Form(False, description="If true, delete existing annotations before importing"),
    sync_taxonomy: bool = Form(True, description="If true, derive and merge taxonomy from annotation classes"),
):
    """
    Import annotations directly to a specific task.
    
    Requires ANNOTATIONS_CREATE permission.
    """
    task_query = select(Task).where(Task.id == task_id, Task.is_deleted == False)
    result = await db.execute(task_query)
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    scene_query = select(Scene).where(Scene.id == task.scene_id)
    result = await db.execute(scene_query)
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found for task {task_id}"
        )
    
    return await import_annotations(
        scene_id=scene.id,
        file=file,
        task_id=task_id,
        overwrite=overwrite,
        sync_taxonomy=sync_taxonomy,
        current_user=current_user,
        db=db
    )





@router.post("/datasets/{dataset_id}/import-annotations")
async def import_dataset_annotations(
    dataset_id: UUID,
    current_user: Annotated[User, Depends(RequirePermissions(Permission.DATASETS_IMPORT))],
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="ZIP file containing per-sensor annotation JSON files"),
    derive_taxonomy: bool = Form(True, description="Automatically derive taxonomy from annotations"),
    overwrite: bool = Form(False, description="Overwrite existing annotations"),
):
    """
    Import annotations for an entire dataset with optional taxonomy derivation.
    
    This endpoint:
    1. Accepts a ZIP file with per-sensor annotation files
    2. Optionally derives a taxonomy from the annotation classes
    3. Creates annotations for all matching scenes/frames
    4. Links the derived taxonomy to the dataset
    
    Expected ZIP structure:
        annotations.zip/
        ├── scene_001/
        │   ├── lidar.json           # 3D annotations for scene_001
        │   ├── camera_front.json    # 2D annotations for camera_front
        │   └── ...
        ├── scene_002/
        │   └── ...
        └── (or flat structure for single scene)
            ├── lidar.json
            └── camera_front.json
    
    Requires DATASETS_IMPORT permission.
    """
    dataset_query = select(Dataset).where(Dataset.id == dataset_id)
    result = await db.execute(dataset_query)
    dataset = result.scalar_one_or_none()
    
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found"
        )
    
    scenes_query = select(Scene).where(Scene.dataset_id == dataset_id, Scene.is_deleted == False)
    result = await db.execute(scenes_query)
    scenes = result.scalars().all()
    
    if not scenes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dataset has no scenes. Import sensor data first."
        )
    
    scene_map = {scene.name: scene for scene in scenes}
    
    try:
        content = await file.read()
        zip_buffer = io.BytesIO(content)
        
        if not zipfile.is_zipfile(zip_buffer):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is not a valid ZIP file"
            )
        
        zip_buffer.seek(0)
        
        annotations_by_scene: Dict[str, Dict[str, dict]] = {}
        all_annotation_files: Dict[str, dict] = {}
        
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            for file_info in zf.infolist():
                if file_info.is_dir():
                    continue
                
                file_path = file_info.filename
                
                if '__MACOSX' in file_path or file_path.startswith('.'):
                    continue
                
                if not file_path.endswith('.json'):
                    continue
                
                parts = file_path.replace('\\', '/').split('/')
                
                if len(parts) >= 2:
                    scene_name = parts[-2]
                    sensor_name = parts[-1].replace('.json', '')
                elif len(parts) == 1:
                    scene_name = scenes[0].name if len(scenes) == 1 else "default"
                    sensor_name = parts[0].replace('.json', '')
                else:
                    continue
                
                try:
                    json_content = zf.read(file_info.filename).decode('utf-8')
                    coco_data = json.loads(json_content)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    continue
                
                if scene_name not in annotations_by_scene:
                    annotations_by_scene[scene_name] = {}
                annotations_by_scene[scene_name][sensor_name] = coco_data
                
                all_annotation_files[sensor_name] = coco_data
        
        if not annotations_by_scene:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid annotation JSON files found in ZIP"
            )
        
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or corrupted ZIP file"
        )
    
    derived_taxonomy = None
    derived_taxonomy_id = None
    
    if derive_taxonomy and all_annotation_files:
        derived_taxonomy = derive_taxonomy_from_annotations(
            all_annotation_files, 
            dataset.name
        )
        
        new_taxonomy = Taxonomy(
            id=uuid4(),
            name=derived_taxonomy["name"],
            description=f"Auto-derived taxonomy from imported annotations for {dataset.name}",
            version="1.0.0",
            classes=derived_taxonomy["classes"],
            skeletons=derived_taxonomy.get("skeletons", {}),
            annotation_rules=derived_taxonomy.get("annotation_rules", {}),
            created_by=current_user.id,
        )
        db.add(new_taxonomy)
        await db.flush()
        
        await db.execute(
            dataset_taxonomy_association.insert().values(
                dataset_id=dataset_id,
                taxonomy_id=new_taxonomy.id
            )
        )
        
        derived_taxonomy_id = str(new_taxonomy.id)
    
    total_imported = 0
    sensors_processed = {}
    errors = []
    scenes_processed = 0
    
    for scene_name_key, sensor_annotations in annotations_by_scene.items():
        scene = None
        for s_name, s in scene_map.items():
            if s_name == scene_name_key or scene_name_key in s_name or s_name in scene_name_key:
                scene = s
                break
        
        if not scene and len(scenes) == 1:
            scene = scenes[0]
        
        if not scene:
            errors.append(f"Scene '{scene_name_key}' not found in dataset")
            continue
        
        task_query = select(Task).where(
            Task.scene_id == scene.id,
            Task.is_deleted == False
        ).order_by(Task.created_at.desc())
        result = await db.execute(task_query)
        task = result.scalar_one_or_none()
        
        if not task:
            task = Task(
                id=uuid4(),
                scene_id=scene.id,
                status="pending",
                stage="annotation",
                created_at=datetime.utcnow(),
            )
            db.add(task)
            await db.flush()
        
        frames_query = select(Frame).where(Frame.scene_id == scene.id).order_by(Frame.frame_index)
        result = await db.execute(frames_query)
        frames = result.scalars().all()
        
        if not frames:
            errors.append(f"Scene '{scene.name}' has no frames")
            continue
        
        frame_id_map = {f.frame_index: f.id for f in frames}
        
        dataset_result = await db.execute(
            select(Dataset).where(Dataset.id == scene.dataset_id)
        )
        dataset = dataset_result.scalar_one_or_none()
        taxonomy = dataset.taxonomy if dataset else None
        resolved_taxonomy_id = task.taxonomy_id or (taxonomy.id if taxonomy else None)

        if overwrite:
            from sqlalchemy import delete
            await db.execute(delete(Annotation2D).where(Annotation2D.task_id == task.id))
            await db.execute(delete(Annotation3D).where(Annotation3D.task_id == task.id))
        
        for sensor_name, coco_data in sensor_annotations.items():
            is_3d = sensor_name.lower() in ['lidar', 'velodyne', 'point_cloud', 'pointcloud']
            
            if is_3d:
                parsed = parse_coco_3d_annotations(coco_data, frame_id_map, taxonomy)
                for ann_data in parsed:
                    ann = Annotation3D(
                        id=uuid4(),
                        task_id=task.id,
                        frame_id=ann_data["frame_id"],
                        class_id=ann_data["class_id"],
                        taxonomy_id=resolved_taxonomy_id,
                        position_x=ann_data["position"][0],
                        position_y=ann_data["position"][1],
                        position_z=ann_data["position"][2],
                        dimension_x=ann_data["dimensions"][0],
                        dimension_y=ann_data["dimensions"][1],
                        dimension_z=ann_data["dimensions"][2],
                        rotation_x=ann_data.get("rotation", [0, 0, 0])[0],
                        rotation_y=ann_data.get("rotation", [0, 0, 0])[1],
                        rotation_z=ann_data.get("rotation", [0, 0, 0])[2],
                        attributes=ann_data.get("attributes", {}),
                        source=AnnotationSource.AUTO,
                        confidence=ann_data.get("confidence", 1.0),
                    )
                    db.add(ann)
                    total_imported += 1
                    sensors_processed[sensor_name] = sensors_processed.get(sensor_name, 0) + 1
            else:
                parsed = parse_coco_2d_annotations(coco_data, sensor_name, frame_id_map, taxonomy)

                track_id_remap: Dict[str, UUID] = {}
                for tr in (coco_data.get("tracks") or []):
                    orig_id = tr.get("id")
                    if orig_id is None:
                        continue
                    new_track = Track2D(
                        id=uuid4(),
                        task_id=task.id,
                        camera_id=sensor_name,
                        class_id=tr.get("class_id") or "unknown",
                        name=tr.get("name"),
                        color=tr.get("color"),
                        start_frame_index=tr.get("start_frame_index"),
                        end_frame_index=tr.get("end_frame_index"),
                        is_interpolated=bool(tr.get("is_interpolated", False)),
                        is_complete=bool(tr.get("is_complete", False)),
                        attributes=tr.get("attributes") or {},
                    )
                    db.add(new_track)
                    track_id_remap[str(orig_id)] = new_track.id

                for ann_data in parsed:
                    resolved_track_id = None
                    orig_track_id = ann_data.get("track_id")
                    if orig_track_id is not None:
                        track_key = str(orig_track_id)
                        resolved_track_id = track_id_remap.get(track_key)
                        if resolved_track_id is None:
                            fallback_track = Track2D(
                                id=uuid4(),
                                task_id=task.id,
                                camera_id=sensor_name,
                                class_id=ann_data["class_id"],
                                is_interpolated=False,
                                is_complete=False,
                                attributes={},
                            )
                            db.add(fallback_track)
                            track_id_remap[track_key] = fallback_track.id
                            resolved_track_id = fallback_track.id

                    ann = Annotation2D(
                        id=uuid4(),
                        task_id=task.id,
                        track_id=resolved_track_id,
                        frame_id=ann_data["frame_id"],
                        camera_id=sensor_name,
                        class_id=ann_data["class_id"],
                        taxonomy_id=resolved_taxonomy_id,
                        type="box2d",
                        data={
                            "bbox": {
                                "x": ann_data["bbox_x"],
                                "y": ann_data["bbox_y"],
                                "width": ann_data["bbox_width"],
                                "height": ann_data["bbox_height"],
                            }
                        },
                        attributes=ann_data.get("attributes", {}),
                        source=AnnotationSource.AUTO.value,
                    )
                    db.add(ann)
                    total_imported += 1
                    sensors_processed[sensor_name] = sensors_processed.get(sensor_name, 0) + 1
        
        scenes_processed += 1
    
    await db.commit()
    
    return {
        "success": True,
        "message": f"Imported {total_imported} annotations for {scenes_processed} scenes",
        "imported_count": total_imported,
        "scenes_processed": scenes_processed,
        "sensors_processed": sensors_processed,
        "derived_taxonomy_id": derived_taxonomy_id,
        "derived_classes": [c["name"] for c in derived_taxonomy["classes"]] if derived_taxonomy else [],
        "errors": errors,
    }
