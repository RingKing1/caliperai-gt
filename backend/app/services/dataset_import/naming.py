"""Smart name generation and folder-to-task matching."""
import re

from app.models.models import Task
from app.services.dataset_import.constants import GENERIC_FOLDER_NAMES


def generate_smart_scene_name(folder_name: str, index: int = 1) -> str:
    """
    Generate a smart scene name from folder name.
    Handles common generic names and cleans up the name.

    Args:
        folder_name: Original folder name
        index: Scene index if multiple scenes

    Returns:
        Smart scene name

    Examples:
        'extracted' -> 'Scene_01'
        'data' -> 'Scene_01'
        'scene123' -> 'Scene_123'
        'urban_downtown_night' -> 'Urban_Downtown_Night'
        'scene-0916_2026-01-16T19-06-11' -> 'Scene_0916'
    """
    generic_names = GENERIC_FOLDER_NAMES

    name = folder_name.strip()

    if name.lower() in generic_names or not name:
        return f"Scene_{str(index).zfill(2)}"

    if 'T' in name and ('-' in name or '_' in name):
        parts = name.split('_')[0].split('-')
        for part in parts:
            if part.isdigit() and len(part) >= 3:
                return f"Scene_{part}"

    cleaned = name.replace('-', '_').replace('.', '_')

    words = [w.capitalize() for w in cleaned.split('_') if w]

    if words and words[0].lower() == 'scene':
        if len(words) > 1 and words[1].isdigit():
            return f"Scene_{words[1]}"
        elif len(words) > 1:
            return '_'.join(words[:3])

    smart_name = '_'.join(words[:3])

    if len(smart_name) < 5:
        smart_name = f"Scene_{str(index).zfill(2)}"

    return smart_name


def generate_smart_task_name(scene_name: str, frame_count: int, task_type: str = "Annot") -> str:
    """
    Generate a smart task name based on scene name and frame range.

    Args:
        scene_name: Name of the scene
        frame_count: Number of frames in the scene
        task_type: Type of task (Annot, Label, QA, Review, etc.)

    Returns:
        Smart task name

    Examples:
        'Urban_Downtown' + 100 frames -> 'Annot_Urban_Downtown_F1-100'
        'Scene_01' + 50 frames -> 'Annot_Scene_01_F1-50'
    """
    clean_scene = scene_name

    if len(clean_scene) > 20:
        parts = clean_scene.split('_')
        clean_scene = '_'.join(parts[:2])

    if frame_count > 0:
        return f"{task_type}_{clean_scene}_F1-{frame_count}"
    else:
        return f"{task_type}_{clean_scene}"



def match_folder_to_task(
    folder_name: str,
    tasks_with_taxonomy: list[tuple[Task, str | None]],
) -> Task | None:
    """Match an export folder name to a task by comparing taxonomy names.

    Export folder format (from build_task_export_folder_name):
        {safe_task_name}__{task_id[:8]}
    where task.name == "{scene_name} - {taxonomy_name}" and safe_task_name is
    the result of re.sub(r"[^a-zA-Z0-9_-]+", "_", task.name).strip("_").

    ' - ' encodes to '_-_', so we split on the LAST occurrence of '_-_' to
    extract the taxonomy part even when the scene name itself contains '-'.
    """
    without_hash = re.sub(r'__[0-9a-f]{8}$', '', folder_name, flags=re.IGNORECASE)

    parts = without_hash.split('_-_', maxsplit=1)
    taxonomy_safe_from_folder = parts[-1] if len(parts) == 2 else without_hash

    for task, taxonomy_name in tasks_with_taxonomy:
        if not taxonomy_name:
            continue
        taxonomy_safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", taxonomy_name).strip("_")
        if taxonomy_safe.lower() == taxonomy_safe_from_folder.lower():
            return task

    return None


