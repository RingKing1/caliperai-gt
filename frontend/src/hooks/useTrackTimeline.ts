import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { useTrackStore } from '@/store/trackStore';
import { annotation3DApi, tracks3DApi } from '@/api/client';
import type { CuboidData, Dimensions3D } from '@/types';
import { validateTrackBinding } from '@/utils/trackValidation';

export interface TrackTimelineNode {
  frameIndex: number;
  displayNumber: number;
  isKeyframe: boolean;
  isTracked: boolean;
  isCurrent: boolean;
  annotationId?: string;
  dimensions?: Dimensions3D;
}

/**
 * crypto.randomUUID() is only exposed in secure contexts (HTTPS / localhost).
 * Annotators commonly open the platform over plain HTTP on the LAN, where the
 * old `trk-<base36>` fallback produced a non-UUID string — the backend rejects
 * it with 422 ("Input should be a valid UUID"), surfacing as the useless
 * "加入/覆盖轨迹失败" toast. Always emit a real v4 UUID.
 */
function generateTrackUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function useTrackTimeline() {
  const {
    task,
    frames,
    currentFrameIndex,
    annotations,
    selection,
    goToFrame,
    selectAnnotation,
    deselectAll,
    updateAnnotation,
    keyframeSamplingEnabled,
    keyframeInterval,
    keyframeStartFrame,
    isKeyframeAt,
  } = useEditorStore();

  const { activeTrackId: storeActiveTrackId, setActiveTrack } = useTrackStore();

  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [trackAnnotations, setTrackAnnotations] = useState<any[]>([]);
  // Track-level refinement flag: Human-refined (true) vs AI-only (false)
  const [isRefined, setIsRefined] = useState(false);
  const [refinementLoading, setRefinementLoading] = useState(false);

  // Pinned Track Session: keeps track session pinned even when switching to MISS frames
  const [pinnedTrackId, setPinnedTrackId] = useState<string | null>(null);
  const [pinnedTrackClass, setPinnedTrackClass] = useState<string>('Object');

  // 1. Identify currently active track from selected annotation or pinned session
  const selectedAnnotationId = selection.selectedAnnotationIds[0] || null;
  const selectedAnnotation = useMemo(() => {
    if (!selectedAnnotationId) return null;
    return annotations.get(selectedAnnotationId) || null;
  }, [selectedAnnotationId, annotations]);

  // When user selects an annotation with track_id:
  // - If no pinned track is set yet, pin it and set store active track
  // - If it belongs to current pinned track, update class info
  // - If it belongs to a different track, do NOT auto-overwrite pinned session so user can Merge or Switch
  useEffect(() => {
    if (selectedAnnotation?.track_id) {
      if (!pinnedTrackId) {
        setPinnedTrackId(selectedAnnotation.track_id);
        setActiveTrack(selectedAnnotation.track_id);
        if (selectedAnnotation.class_id) {
          setPinnedTrackClass(selectedAnnotation.class_id);
        }
        setIsOpen(true);
      } else if (selectedAnnotation.track_id === pinnedTrackId) {
        if (selectedAnnotation.class_id) {
          setPinnedTrackClass(selectedAnnotation.class_id);
        }
      }
    }
  }, [selectedAnnotation?.track_id, selectedAnnotation?.class_id, pinnedTrackId, setActiveTrack]);

  // When storeActiveTrackId is cleared to null (e.g. user clicked empty space, point cloud, or pressed Esc),
  // hide the track timeline bar and clear pinned session.
  useEffect(() => {
    if (storeActiveTrackId === null) {
      setPinnedTrackId(null);
      setIsOpen(false);
    } else if (storeActiveTrackId && storeActiveTrackId !== pinnedTrackId) {
      setPinnedTrackId(storeActiveTrackId);
      setIsOpen(true);
    }
  }, [storeActiveTrackId, pinnedTrackId]);

  const activeTrackId = (isOpen && (pinnedTrackId || storeActiveTrackId)) ? (pinnedTrackId || storeActiveTrackId) : null;

  const closeTimeline = useCallback(() => {
    setIsOpen(false);
    setPinnedTrackId(null);
    setActiveTrack(null);
  }, [setActiveTrack]);

  const switchTrack = useCallback((newTrackId: string) => {
    setPinnedTrackId(newTrackId);
    setActiveTrack(newTrackId);
    setIsOpen(true);
  }, [setActiveTrack]);

  // 2. Build fast lookup: frameId <-> frameIndex
  const frameIdToIndex = useMemo(() => {
    const idToIdx = new Map<string, number>();
    frames.forEach((f, idx) => {
      idToIdx.set(f.id, idx);
    });
    return idToIdx;
  }, [frames]);

  // 3. Fetch all annotations for this track across the whole task
  const fetchTrackAnnotations = useCallback(async (trackId: string) => {
    if (!task?.id) return;
    setIsLoading(true);
    try {
      const list = await annotation3DApi.list(task.id, undefined, trackId);
      setTrackAnnotations(list || []);
    } catch (err) {
      console.error('[useTrackTimeline] Failed to fetch track annotations:', err);
    } finally {
      setIsLoading(false);
    }
  }, [task?.id]);

  // Load the refinement flag for the current track. Sparse API: a track with
  // no row is AI-only, so a miss simply means `false`.
  const fetchRefinement = useCallback(async (trackId: string) => {
    if (!task?.id) return;
    try {
      const rows = await tracks3DApi.list(task.id);
      const row = (rows || []).find((r) => r.track_id === trackId);
      setIsRefined(!!row?.is_refined);
    } catch (err) {
      console.error('[useTrackTimeline] Failed to fetch refinement state:', err);
    }
  }, [task?.id]);

  const toggleRefinement = useCallback(async () => {
    if (!activeTrackId) return;
    const next = !isRefined;
    setRefinementLoading(true);
    setIsRefined(next); // optimistic
    try {
      await tracks3DApi.setRefined(activeTrackId, next);
    } catch (err) {
      console.error('[useTrackTimeline] Failed to set refinement state:', err);
      setIsRefined(!next); // revert
    } finally {
      setRefinementLoading(false);
    }
  }, [activeTrackId, isRefined]);

  useEffect(() => {
    if (activeTrackId) {
      fetchTrackAnnotations(activeTrackId);
      fetchRefinement(activeTrackId);
    } else {
      setTrackAnnotations([]);
      setIsRefined(false);
    }
  }, [activeTrackId, fetchTrackAnnotations]);

  // 4. Map annotations by frame index
  const { frameIndexToAnn, trackedFrameIndices, minFrameIndex, maxFrameIndex } = useMemo(() => {
    const map = new Map<number, any>();
    const indices: number[] = [];

    trackAnnotations.forEach((ann) => {
      const idx = frameIdToIndex.get(ann.frame_id);
      if (idx !== undefined) {
        map.set(idx, ann);
        indices.push(idx);
      }
    });

    indices.sort((a, b) => a - b);
    const minIdx = indices.length > 0 ? indices[0] : currentFrameIndex;
    const maxIdx = indices.length > 0 ? indices[indices.length - 1] : currentFrameIndex;

    return {
      frameIndexToAnn: map,
      trackedFrameIndices: indices,
      minFrameIndex: minIdx,
      maxFrameIndex: maxIdx,
    };
  }, [trackAnnotations, frameIdToIndex, currentFrameIndex]);

  // Current frame status relative to this track
  const isCurrentFrameTracked = frameIndexToAnn.has(currentFrameIndex);
  const currentFrameDisplayNumber = (frames[currentFrameIndex]?.frame_index ?? currentFrameIndex) + 1;

  // Active track category name
  const currentClassId = useMemo(() => {
    if (selectedAnnotation && selectedAnnotation.track_id === activeTrackId && selectedAnnotation.class_id) {
      return selectedAnnotation.class_id;
    }
    if (pinnedTrackClass && pinnedTrackClass !== 'Object') {
      return pinnedTrackClass;
    }
    for (const ann of trackAnnotations) {
      if (ann.class_id) return ann.class_id;
    }
    return pinnedTrackClass || 'Object';
  }, [selectedAnnotation, activeTrackId, pinnedTrackClass, trackAnnotations]);

  // 5. Generate timeline nodes based on whether keyframe sampling mode is enabled
  const timelineNodes = useMemo<TrackTimelineNode[]>(() => {
    if (frames.length === 0 || !activeTrackId) return [];

    if (keyframeSamplingEnabled) {
      // ---- Keyframe Mode ----
      const interval = Math.max(1, keyframeInterval);
      const allKeyframes: number[] = [];
      for (let i = keyframeStartFrame; i < frames.length; i += interval) {
        allKeyframes.push(i);
      }

      // Bound keyframes around the track's lifespan with margin
      const margin = 2 * interval;
      const lower = Math.max(keyframeStartFrame, minFrameIndex - margin);
      const upper = Math.min(frames.length - 1, maxFrameIndex + margin);

      return allKeyframes
        .filter((idx) => idx >= lower && idx <= upper)
        .map((idx) => {
          const ann = frameIndexToAnn.get(idx);
          const cuboid = ann?.data as CuboidData | undefined;
          return {
            frameIndex: idx,
            displayNumber: (frames[idx]?.frame_index ?? idx) + 1,
            isKeyframe: true,
            isTracked: !!ann,
            isCurrent: idx === currentFrameIndex,
            annotationId: ann?.id,
            dimensions: cuboid?.dimensions,
          };
        });
    } else {
      // ---- Normal Frames Mode ----
      // Range: [min - 15, max + 15] clamped to valid frame indices
      const start = Math.max(0, minFrameIndex - 15);
      const end = Math.min(frames.length - 1, maxFrameIndex + 15);

      const nodes: TrackTimelineNode[] = [];
      for (let i = start; i <= end; i++) {
        const ann = frameIndexToAnn.get(i);
        const cuboid = ann?.data as CuboidData | undefined;
        nodes.push({
          frameIndex: i,
          displayNumber: (frames[i]?.frame_index ?? i) + 1,
          isKeyframe: isKeyframeAt(i),
          isTracked: !!ann,
          isCurrent: i === currentFrameIndex,
          annotationId: ann?.id,
          dimensions: cuboid?.dimensions,
        });
      }
      return nodes;
    }
  }, [
    frames,
    activeTrackId,
    keyframeSamplingEnabled,
    keyframeInterval,
    keyframeStartFrame,
    minFrameIndex,
    maxFrameIndex,
    frameIndexToAnn,
    currentFrameIndex,
    isKeyframeAt,
  ]);

  // 6. Check selection state relative to active track
  // Is selected object from the active track? (Yellow frame object)
  const isSelectedInActiveTrack = useMemo(() => {
    if (!selectedAnnotation || !activeTrackId) return false;
    return selectedAnnotation.track_id === activeTrackId;
  }, [selectedAnnotation, activeTrackId]);

  // Is selected object from ANOTHER track? (Candidate for merge or single re-assign)
  const selectedOtherTrackId = useMemo(() => {
    if (!selectedAnnotation || !activeTrackId) return null;
    if (selectedAnnotation.track_id && selectedAnnotation.track_id !== activeTrackId) {
      return selectedAnnotation.track_id;
    }
    return null;
  }, [selectedAnnotation, activeTrackId]);

  // Candidate annotation in current frame that doesn't belong to this track yet
  const candidateToLink = useMemo(() => {
    if (!activeTrackId) return null;
    if (!selectedAnnotation) return null;
    if (selectedAnnotation.track_id !== activeTrackId) {
      return selectedAnnotation;
    }
    return null;
  }, [activeTrackId, selectedAnnotation]);

  // Jump to specific frame, automatically selecting the track annotation if present
  const jumpToFrame = useCallback(
    (index: number) => {
      if (index >= 0 && index < frames.length) {
        goToFrame(index);
        const targetAnn = frameIndexToAnn.get(index);
        if (targetAnn?.id) {
          selectAnnotation(targetAnn.id);
        } else {
          deselectAll();
        }
      }
    },
    [goToFrame, frames.length, frameIndexToAnn, selectAnnotation, deselectAll]
  );

  // Jump to start or end of this track
  const jumpToTrackStart = useCallback(() => {
    if (trackedFrameIndices.length > 0) {
      jumpToFrame(trackedFrameIndices[0]);
    }
  }, [trackedFrameIndices, jumpToFrame]);

  const jumpToTrackEnd = useCallback(() => {
    if (trackedFrameIndices.length > 0) {
      jumpToFrame(trackedFrameIndices[trackedFrameIndices.length - 1]);
    }
  }, [trackedFrameIndices, jumpToFrame]);

  // 6. Compute action frame scope based on keyframe sampling vs regular frame mode
  const getTargetScopeFrameIndices = useCallback((): number[] => {
    if (keyframeSamplingEnabled) {
      const interval = Math.max(1, keyframeInterval);
      // Keyframe scope: from current keyframe to the frame before next keyframe [current_kf, next_kf)
      const offset = (currentFrameIndex - keyframeStartFrame) % interval;
      const startIdx = offset >= 0 && offset < interval
        ? currentFrameIndex - offset
        : currentFrameIndex;
      const endIdx = Math.min(frames.length, startIdx + interval);
      const indices: number[] = [];
      for (let i = startIdx; i < endIdx; i++) {
        indices.push(i);
      }
      return indices;
    }
    // Regular frame mode: strictly current single frame
    return [currentFrameIndex];
  }, [keyframeSamplingEnabled, keyframeInterval, keyframeStartFrame, currentFrameIndex, frames.length]);

  // Next keyframe display number helper for tooltips/toast
  const nextKeyframeDisplayNumber = useMemo(() => {
    if (!keyframeSamplingEnabled) return currentFrameDisplayNumber;
    const interval = Math.max(1, keyframeInterval);
    const offset = (currentFrameIndex - keyframeStartFrame) % interval;
    const startIdx = offset >= 0 && offset < interval ? currentFrameIndex - offset : currentFrameIndex;
    const endIdx = Math.min(frames.length - 1, startIdx + interval - 1);
    return (frames[endIdx]?.frame_index ?? endIdx) + 1;
  }, [keyframeSamplingEnabled, keyframeInterval, keyframeStartFrame, currentFrameIndex, frames, currentFrameDisplayNumber]);

  // Track status of the active frame/keyframe (Yellow TRACK vs Gray MISS)
  // Strictly matches the visual node color (isTracked) of the current frame on the timeline
  const isCurrentScopeTracked = isCurrentFrameTracked;

  // 7. Add / Overwrite candidate annotation (and its scope) into this track
  const addToTrack = useCallback(
    async (targetAnnId?: string): Promise<{
      success: boolean;
      error?: string;
      warning?: string;
      isOverwrite?: boolean;
      overwrittenCount?: number;
      newTrackId?: string;
    }> => {
      const annId = targetAnnId || candidateToLink?.id;
      if (!annId || !activeTrackId) {
        return { success: false, error: '未找到待关联物体或当前未选定主轨迹' };
      }

      const candidateAnn = annotations.get(annId) || (candidateToLink?.id === annId ? candidateToLink : null);
      if (!candidateAnn) {
        return { success: false, error: '未找到待关联物体数据' };
      }

      // Industrial-grade validation with allowOverwrite=true
      const validation = validateTrackBinding({
        targetTrackId: activeTrackId,
        candidateAnnotation: candidateAnn,
        allAnnotations: annotations,
        trackAnnotations,
        frames,
        lockedAnnotationIds: useEditorStore.getState().lockedAnnotationIds,
        allowOverwrite: true,
      });

      if (!validation.valid) {
        return { success: false, error: validation.error };
      }

      setIsLoading(true);
      try {
        const scopeIndices = getTargetScopeFrameIndices();
        const scopeFrameIdSet = new Set<string>(
          scopeIndices.map((idx) => frames[idx]?.id).filter(Boolean)
        );

        // Find existing annotations belonging to activeTrackId in this scope
        const oldAnnsInScope = trackAnnotations.filter((a) => a.id !== candidateAnn.id && scopeFrameIdSet.has(a.frame_id));

        const bulkPayload: Array<{ id: string; track_id: string | null }> = [];
        let newTrackId: string | undefined;

        if (oldAnnsInScope.length > 0) {
          // Overwrite mode: assign fresh non-repeating UUID to old evicted annotations
          newTrackId = generateTrackUuid();

          oldAnnsInScope.forEach((old) => {
            bulkPayload.push({ id: old.id, track_id: newTrackId! });
          });
        }

        // Bind candidate annotation to activeTrackId
        bulkPayload.push({ id: candidateAnn.id, track_id: activeTrackId });

        // If in keyframe mode and candidate belongs to a source track,
        // bring along other annotations of that source track inside this keyframe scope
        if (keyframeSamplingEnabled && candidateAnn.track_id && candidateAnn.track_id !== activeTrackId) {
          const srcTrackId = candidateAnn.track_id;
          const annList = Array.from(annotations.values());
          annList.forEach((srcAnn) => {
            if (
              srcAnn.track_id === srcTrackId &&
              srcAnn.id !== candidateAnn.id &&
              scopeFrameIdSet.has(srcAnn.frame_id)
            ) {
              if (!bulkPayload.some((b) => b.id === srcAnn.id)) {
                bulkPayload.push({ id: srcAnn.id, track_id: activeTrackId });
              }
            }
          });
        }

        await annotation3DApi.updateBulk(bulkPayload);

        bulkPayload.forEach((item) => {
          updateAnnotation(item.id, { track_id: item.track_id ?? undefined });
        });

        await fetchTrackAnnotations(activeTrackId);

        return {
          success: true,
          warning: validation.warning,
          isOverwrite: oldAnnsInScope.length > 0,
          overwrittenCount: oldAnnsInScope.length,
          newTrackId,
        };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to add/overwrite annotation to track:', err);
        return { success: false, error: '加入/覆盖轨迹失败，请检查网络或后端日志' };
      } finally {
        setIsLoading(false);
      }
    },
    [
      candidateToLink,
      activeTrackId,
      annotations,
      trackAnnotations,
      frames,
      keyframeSamplingEnabled,
      getTargetScopeFrameIndices,
      updateAnnotation,
      fetchTrackAnnotations,
    ]
  );

  // 8. Detach / split annotation from current track (Silent, no prompt, assigns new UUID)
  const detachFromTrack = useCallback(
    async (): Promise<{ success: boolean; count?: number; newTrackId?: string; error?: string }> => {
      if (!activeTrackId) return { success: false, error: '未选定主轨迹' };

      const scopeIndices = getTargetScopeFrameIndices();
      const scopeFrameIdSet = new Set<string>(
        scopeIndices.map((idx) => frames[idx]?.id).filter(Boolean)
      );

      // Find all annotations belonging to activeTrackId within the scope
      const annsToDetach = trackAnnotations.filter((a) => scopeFrameIdSet.has(a.frame_id));

      if (annsToDetach.length === 0) {
        return { success: false, error: '当前帧/区间未发现属于该轨迹的标注' };
      }

      setIsLoading(true);
      try {
        const newTrackId = generateTrackUuid();

        const bulkPayload = annsToDetach.map((ann) => ({
          id: ann.id,
          track_id: newTrackId,
        }));

        await annotation3DApi.updateBulk(bulkPayload);

        bulkPayload.forEach((item) => {
          updateAnnotation(item.id, { track_id: item.track_id });
        });

        await fetchTrackAnnotations(activeTrackId);
        return { success: true, count: bulkPayload.length, newTrackId };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to detach annotation(s) from track:', err);
        return { success: false, error: '移出失败，请重试' };
      } finally {
        setIsLoading(false);
      }
    },
    [
      activeTrackId,
      frames,
      getTargetScopeFrameIndices,
      trackAnnotations,
      updateAnnotation,
      fetchTrackAnnotations,
    ]
  );

  // 9. Merge another track (sourceTrackId) into current activeTrackId (Silent, Overwrites active scope, Fills gaps elsewhere)
  const mergeWithTrack = useCallback(
    async (sourceTrackId: string): Promise<{
      success: boolean;
      error?: string;
      warning?: string;
      mergedCount: number;
      conflictCount: number;
      overwrittenCount: number;
      sourceTrackId?: string;
      newTrackId?: string;
    }> => {
      if (!activeTrackId || !sourceTrackId || activeTrackId === sourceTrackId || !task?.id) {
        return { success: false, error: '无效的合并轨迹目标', mergedCount: 0, conflictCount: 0, overwrittenCount: 0 };
      }

      setIsLoading(true);
      try {
        // Fetch all annotations for sourceTrackId
        const sourceList = await annotation3DApi.list(task.id, undefined, sourceTrackId);
        if (!sourceList || sourceList.length === 0) {
          return { success: false, error: '未找到次轨迹的标注数据', mergedCount: 0, conflictCount: 0, overwrittenCount: 0 };
        }

        // Verify class consistency
        const targetClass = trackAnnotations[0]?.class_id || selectedAnnotation?.class_id;
        const invalidClassAnn = sourceList.find((a: any) => targetClass && a.class_id && a.class_id !== targetClass);
        if (invalidClassAnn) {
          return {
            success: false,
            error: `类别不匹配：源轨迹包含类别 [${invalidClassAnn.class_id}]，而主轨迹类别为 [${targetClass}]，禁止合并！`,
            mergedCount: 0,
            conflictCount: 0,
            overwrittenCount: 0,
          };
        }

        // Build lookup of frame_ids that already exist in activeTrack
        const activeFrameIdSet = new Set<string>();
        trackAnnotations.forEach((ann) => {
          if (ann.frame_id) {
            activeFrameIdSet.add(ann.frame_id);
          }
        });

        // Determine current scope frame IDs (single frame or keyframe interval)
        const scopeIndices = getTargetScopeFrameIndices();
        const scopeFrameIdSet = new Set<string>(
          scopeIndices.map((idx) => frames[idx]?.id).filter(Boolean)
        );

        const bulkPayload: Array<{ id: string; track_id: string | null }> = [];
        let mergedCount = 0;
        let conflictCount = 0;
        let overwrittenCount = 0;
        let newTrackId: string | undefined;

        // Check if main track currently has annotations in scope that should be overwritten
        const oldAnnsInScope = trackAnnotations.filter((a) => scopeFrameIdSet.has(a.frame_id));
        const sourceAnnsInScope = sourceList.filter((a: any) => scopeFrameIdSet.has(a.frame_id));

        if (oldAnnsInScope.length > 0 && sourceAnnsInScope.length > 0) {
          newTrackId = generateTrackUuid();

          oldAnnsInScope.forEach((old) => {
            bulkPayload.push({ id: old.id, track_id: newTrackId! });
            overwrittenCount++;
          });
        }

        // Option A: Strictly merge annotations of sourceTrackId that fall within current scope [current_kf, next_kf) or single frame
        (sourceList || []).forEach((ann: any) => {
          if (scopeFrameIdSet.has(ann.frame_id)) {
            mergedCount++;
            bulkPayload.push({
              id: ann.id,
              track_id: activeTrackId,
            });
          }
        });

        // Handle candidate annotation in current frame if not already included
        if (
          candidateToLink &&
          candidateToLink.track_id === sourceTrackId &&
          !bulkPayload.some((b) => b.id === candidateToLink.id)
        ) {
          mergedCount++;
          bulkPayload.push({
            id: candidateToLink.id,
            track_id: activeTrackId,
          });
        }

        if (bulkPayload.length > 0) {
          await annotation3DApi.updateBulk(bulkPayload);
        }

        // Update editorStore memory
        bulkPayload.forEach((item) => {
          updateAnnotation(item.id, { track_id: item.track_id ?? undefined });
        });

        // Refresh active track annotations
        await fetchTrackAnnotations(activeTrackId);

        return {
          success: true,
          mergedCount,
          conflictCount,
          overwrittenCount,
          sourceTrackId,
          newTrackId,
        };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to merge tracks:', err);
        return { success: false, error: '轨迹合并网络请求异常，请检查后端服务', mergedCount: 0, conflictCount: 0, overwrittenCount: 0 };
      } finally {
        setIsLoading(false);
      }
    },
    [
      activeTrackId,
      task?.id,
      trackAnnotations,
      selectedAnnotation,
      frames,
      getTargetScopeFrameIndices,
      candidateToLink,
      updateAnnotation,
      fetchTrackAnnotations,
    ]
  );

  // 10. One-click sync dimensions across all track objects
  const syncDimensions = useCallback(
    async (targetDims: Dimensions3D) => {
      if (!activeTrackId || trackAnnotations.length === 0) return { success: false, count: 0 };

      const targetH = targetDims.height;
      const targetW = targetDims.width;
      const targetL = targetDims.length;

      const bulkPayload = trackAnnotations.map((ann) => {
        const oldData = (ann.data || {}) as any;
        const oldCenter = oldData.center || { x: 0, y: 0, z: 0 };
        const oldDims = (oldData.dimensions || {}) as Partial<Dimensions3D>;
        const oldH = typeof oldDims.height === 'number' ? oldDims.height : targetH;

        // Preserve ground alignment: bottomZ = oldCenter.z - (oldH / 2)
        // newCenterZ = bottomZ + (targetH / 2)
        const newCenterZ = oldCenter.z - oldH / 2 + targetH / 2;

        return {
          id: ann.id,
          data: {
            ...oldData,
            center: { ...oldCenter, z: newCenterZ },
            dimensions: { length: targetL, width: targetW, height: targetH },
          },
        };
      });

      try {
        await annotation3DApi.updateBulk(bulkPayload);

        // Also update annotations in editorStore memory if present in current frame
        annotations.forEach((ann, id) => {
          if (ann.track_id === activeTrackId && ann.type === 'cuboid') {
            const oldData = ann.data as CuboidData;
            const oldH = oldData?.dimensions?.height || targetH;
            const newCenterZ = oldData.center.z - oldH / 2 + targetH / 2;
            updateAnnotation(id, {
              data: {
                ...oldData,
                center: { ...oldData.center, z: newCenterZ },
                dimensions: { length: targetL, width: targetW, height: targetH },
              },
            });
          }
        });

        await fetchTrackAnnotations(activeTrackId);
        return { success: true, count: bulkPayload.length };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to sync track dimensions:', err);
        return { success: false, count: 0 };
      }
    },
    [activeTrackId, trackAnnotations, annotations, updateAnnotation, fetchTrackAnnotations]
  );

  // Active object's current dimensions as default baseline (fallback to track's any annotation)
  const baselineDimensions = useMemo<Dimensions3D | null>(() => {
    if (selectedAnnotation && selectedAnnotation.track_id === activeTrackId && selectedAnnotation.type === 'cuboid') {
      const cuboid = selectedAnnotation.data as CuboidData | undefined;
      if (cuboid?.dimensions) return cuboid.dimensions;
    }
    for (const ann of trackAnnotations) {
      const cuboid = ann.data as CuboidData | undefined;
      if (cuboid?.dimensions?.length && cuboid?.dimensions?.width && cuboid?.dimensions?.height) {
        return cuboid.dimensions;
      }
    }
    return null;
  }, [selectedAnnotation, activeTrackId, trackAnnotations]);

  return {
    isOpen,
    setIsOpen,
    closeTimeline,
    switchTrack,
    isLoading,
    activeTrackId,
    currentClassId,
    selectedAnnotation,
    isSelectedInActiveTrack,
    selectedOtherTrackId,
    timelineNodes,
    trackedCount: trackedFrameIndices.length,
    totalNodesCount: timelineNodes.length,
    currentFrameDisplayNumber,
    nextKeyframeDisplayNumber,
    isCurrentFrameTracked,
    isCurrentScopeTracked,
    keyframeSamplingEnabled,
    keyframeInterval,
    candidateToLink,
    baselineDimensions,
    jumpToFrame,
    jumpToTrackStart,
    jumpToTrackEnd,
    addToTrack,
    detachFromTrack,
    mergeWithTrack,
    syncDimensions,
    isRefined,
    refinementLoading,
    toggleRefinement,
    refreshTrack: () => activeTrackId && fetchTrackAnnotations(activeTrackId),
  };
}
