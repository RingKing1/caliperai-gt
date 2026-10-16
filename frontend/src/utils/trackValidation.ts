/**
 * Track Association & Validation Utilities
 * 
 * Enforces industrial-grade consistency & robustness constraints for 3D trajectory tracking:
 * 1. Temporal Exclusivity (One Object Per Frame Per Track)
 * 2. Class Invariance (Category Consistency across Track)
 * 3. Rigid Body Dimension Stability & Anomaly Detection
 * 4. Kinematic Sanity & Teleportation Detection (Max Speed / ID Switch Prevention)
 * 5. Temporal Non-Overlap & Collision Isolation on Merge
 */

import type { Annotation, CuboidData, Frame } from '@/types';

export interface TrackBindingValidationParams {
  /** Target track ID to link or assign to */
  targetTrackId: string;
  /** Candidate annotation to be bound */
  candidateAnnotation: Annotation;
  /** Pool of all annotations (e.g. from editorStore.annotations) */
  allAnnotations: Map<string, Annotation> | Annotation[];
  /** Target frame ID (defaults to candidateAnnotation.frame_id) */
  targetFrameId?: string;
  /** Optional track annotations if already loaded */
  trackAnnotations?: Annotation[];
  /** Frames list to determine frame indices and display numbers */
  frames?: Frame[];
  /** Optional QA locked annotation IDs */
  lockedAnnotationIds?: Set<string>;
  /** When true, same-frame collision will not trigger hard error; allows overwriting */
  allowOverwrite?: boolean;
}

export interface TrackBindingValidationResult {
  valid: boolean;
  /** Hard constraint error message that blocks the operation */
  error?: string;
  /** Soft constraint warning that advises caution */
  warning?: string;
  /** Conflicting annotation ID on the same frame if any */
  conflictingAnnotationId?: string;
  /** Frame display index/number where conflict or reference occurred */
  frameDisplayNumber?: number | string;
  /** Suggested dimension sync values from track baseline */
  suggestedDimensions?: { length: number; width: number; height: number };
}

export interface TrackMergeValidationParams {
  sourceTrackId: string;
  targetTrackId: string;
  allAnnotations: Map<string, Annotation> | Annotation[];
  sourceAnnotations?: Annotation[];
  targetAnnotations?: Annotation[];
  frames?: Frame[];
}

export interface TrackMergeValidationResult {
  valid: boolean;
  error?: string;
  warning?: string;
  overlappingFrameIds: string[];
  overlappingCount: number;
}

/**
 * Helper to get an array of annotations from Map or Array
 */
function toAnnotationList(annotations: Map<string, Annotation> | Annotation[]): Annotation[] {
  return annotations instanceof Map ? Array.from(annotations.values()) : annotations;
}

/**
 * Validate linking an annotation to a target track
 */
export function validateTrackBinding(params: TrackBindingValidationParams): TrackBindingValidationResult {
  const {
    targetTrackId,
    candidateAnnotation,
    allAnnotations,
    targetFrameId = candidateAnnotation.frame_id,
    trackAnnotations,
    frames,
    lockedAnnotationIds,
  } = params;

  if (!targetTrackId) {
    return { valid: false, error: '目标轨迹 ID 不能为空' };
  }

  // 0. QA Lock Protection
  if (lockedAnnotationIds && lockedAnnotationIds.has(candidateAnnotation.id)) {
    return { valid: false, error: '该标注已通过 QA 审核并锁定，禁止更改轨迹关联！' };
  }

  const annList = toAnnotationList(allAnnotations);

  // Collect all annotations currently belonging to the target track (excluding the candidate itself)
  const existingTrackAnns = trackAnnotations && trackAnnotations.length > 0
    ? trackAnnotations.filter((a) => a.id !== candidateAnnotation.id)
    : annList.filter((a) => a.track_id === targetTrackId && a.id !== candidateAnnotation.id);

  // 1. Hard Constraint: Temporal Exclusivity (One Object Per Frame Per Track)
  // Check if target track already has an annotation on the specified frame
  const conflictingAnn = existingTrackAnns.find(
    (a) => (a.frame_id === targetFrameId || (targetFrameId && a.frame_id === targetFrameId))
  );

  if (conflictingAnn) {
    let frameLabel = targetFrameId;
    if (frames && frames.length > 0) {
      const fObj = frames.find((f) => f.id === targetFrameId);
      if (fObj) {
        frameLabel = `第 ${fObj.frame_index + 1} 帧`;
      }
    }
    const shortTrack = targetTrackId.replace(/-/g, '').slice(0, 6).toUpperCase();
    if (!params.allowOverwrite) {
      return {
        valid: false,
        error: `轨迹冲突：目标轨迹 #${shortTrack} 在 ${frameLabel} 已存在标注物体 [${conflictingAnn.class_id || 'Object'}]。同一时刻一条轨迹有且仅能绑定一个物体！`,
        conflictingAnnotationId: conflictingAnn.id,
        frameDisplayNumber: frameLabel,
      };
    }
  }

  // 2. Hard Constraint: Class Invariance (Category Consistency across Track)
  if (existingTrackAnns.length > 0) {
    const trackClassId = existingTrackAnns[0].class_id;
    if (trackClassId && candidateAnnotation.class_id && trackClassId !== candidateAnnotation.class_id) {
      const shortTrack = targetTrackId.replace(/-/g, '').slice(0, 6).toUpperCase();
      return {
        valid: false,
        error: `类别冲突：当前物体类别为 [${candidateAnnotation.class_id}]，而目标轨迹 #${shortTrack} 的类别为 [${trackClassId}]。同一轨迹内所有帧的物体类别必须严格一致！`,
      };
    }
  }

  // Soft Checks (Warnings)
  let warning: string | undefined;
  let suggestedDimensions: { length: number; width: number; height: number } | undefined;

  const candidateCuboid = candidateAnnotation.type === 'cuboid' ? (candidateAnnotation.data as CuboidData) : null;
  const trackCuboids = existingTrackAnns
    .filter((a) => a.type === 'cuboid' && a.data)
    .map((a) => a.data as CuboidData);

  if (candidateCuboid && trackCuboids.length > 0) {
    // 3. Soft Constraint: Rigid Body Dimension Stability
    const avgDims = trackCuboids.reduce(
      (acc, c) => ({
        length: acc.length + c.dimensions.length,
        width: acc.width + c.dimensions.width,
        height: acc.height + c.dimensions.height,
      }),
      { length: 0, width: 0, height: 0 }
    );
    avgDims.length /= trackCuboids.length;
    avgDims.width /= trackCuboids.length;
    avgDims.height /= trackCuboids.length;
    suggestedDimensions = avgDims;

    const cDims = candidateCuboid.dimensions;
    const diffL = Math.abs(cDims.length - avgDims.length);
    const diffW = Math.abs(cDims.width - avgDims.width);
    const diffH = Math.abs(cDims.height - avgDims.height);
    const maxRatio = Math.max(diffL / avgDims.length, diffW / avgDims.width, diffH / avgDims.height);

    if (maxRatio > 0.25 || diffL > 0.5 || diffW > 0.4 || diffH > 0.4) {
      warning = `尺寸突变提醒：当前物体尺寸 (${cDims.length.toFixed(1)}×${cDims.width.toFixed(1)}×${cDims.height.toFixed(1)}m) 与轨迹均值 (${avgDims.length.toFixed(1)}×${avgDims.width.toFixed(1)}×${avgDims.height.toFixed(1)}m) 偏差达 ${(maxRatio * 100).toFixed(0)}%，建议检查或同步尺寸。`;
    }

    // 4. Soft Constraint: Kinematic Jump / Teleportation Sanity Check
    if (frames && frames.length > 0 && candidateCuboid.center) {
      const frameIndexMap = new Map<string, number>();
      frames.forEach((f) => frameIndexMap.set(f.id, f.frame_index));

      const candidateIdx = frameIndexMap.get(targetFrameId);
      if (candidateIdx !== undefined) {
        // Find temporally closest annotation in the track
        let minFrameDiff = Infinity;
        let closestAnn: Annotation | null = null;

        for (const ann of existingTrackAnns) {
          const idx = frameIndexMap.get(ann.frame_id);
          if (idx !== undefined) {
            const diff = Math.abs(idx - candidateIdx);
            if (diff < minFrameDiff) {
              minFrameDiff = diff;
              closestAnn = ann;
            }
          }
        }

        if (closestAnn && closestAnn.type === 'cuboid' && minFrameDiff <= 2) {
          const closestCenter = (closestAnn.data as CuboidData).center;
          const candCenter = candidateCuboid.center;
          const dist = Math.hypot(
            candCenter.x - closestCenter.x,
            candCenter.y - closestCenter.y,
            candCenter.z - closestCenter.z
          );

          const isPedestrian = candidateAnnotation.class_id?.toLowerCase().includes('pedestrian') ||
                               candidateAnnotation.class_id?.toLowerCase().includes('person');
          const maxAllowedDist = isPedestrian ? 3.5 * minFrameDiff : 12.0 * minFrameDiff;

          if (dist > maxAllowedDist) {
            const warnMsg = `时空跳变提醒：与相隔 ${minFrameDiff} 帧的目标空间距离高达 ${dist.toFixed(1)}m (速度异常)，可能发生 ID 串线，请核对是否为同一目标。`;
            warning = warning ? `${warning} ${warnMsg}` : warnMsg;
          }
        }
      }
    }
  }

  return {
    valid: true,
    warning,
    suggestedDimensions,
  };
}

/**
 * Validate merging two tracks
 */
export function validateTrackMerge(params: TrackMergeValidationParams): TrackMergeValidationResult {
  const {
    sourceTrackId,
    targetTrackId,
    allAnnotations,
    sourceAnnotations,
    targetAnnotations,
  } = params;

  if (!sourceTrackId || !targetTrackId) {
    return {
      valid: false,
      error: '源轨迹 ID 或目标轨迹 ID 不能为空',
      overlappingFrameIds: [],
      overlappingCount: 0,
    };
  }

  if (sourceTrackId === targetTrackId) {
    return {
      valid: false,
      error: '无法将轨迹合并到自身',
      overlappingFrameIds: [],
      overlappingCount: 0,
    };
  }

  const annList = toAnnotationList(allAnnotations);

  const srcAnns = sourceAnnotations && sourceAnnotations.length > 0
    ? sourceAnnotations
    : annList.filter((a) => a.track_id === sourceTrackId);

  const tgtAnns = targetAnnotations && targetAnnotations.length > 0
    ? targetAnnotations
    : annList.filter((a) => a.track_id === targetTrackId);

  // Check Class Consistency
  const srcClass = srcAnns[0]?.class_id;
  const tgtClass = tgtAnns[0]?.class_id;

  if (srcClass && tgtClass && srcClass !== tgtClass) {
    return {
      valid: false,
      error: `类别不匹配：源轨迹类别为 [${srcClass}]，而目标轨迹类别为 [${tgtClass}]，禁止合并不同类别的轨迹！`,
      overlappingFrameIds: [],
      overlappingCount: 0,
    };
  }

  // Check Overlapping Frames
  const targetFrameSet = new Set(tgtAnns.map((a) => a.frame_id).filter(Boolean));
  const overlappingFrameIds: string[] = [];

  srcAnns.forEach((a) => {
    if (a.frame_id && targetFrameSet.has(a.frame_id)) {
      overlappingFrameIds.push(a.frame_id);
    }
  });

  const overlappingCount = overlappingFrameIds.length;
  let warning: string | undefined;

  if (overlappingCount > 0) {
    warning = `检测到 ${overlappingCount} 处同帧重叠冲突。合并时将以目标轨迹为主，冲突帧的源轨迹标注将保持原状或解除关联，不会产生同帧双框。`;
  }

  return {
    valid: true,
    warning,
    overlappingFrameIds,
    overlappingCount,
  };
}
