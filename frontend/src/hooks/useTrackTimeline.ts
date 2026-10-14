import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { annotation3DApi } from '@/api/client';
import type { CuboidData, Dimensions3D } from '@/types';

export interface TrackTimelineNode {
  frameIndex: number;
  displayNumber: number;
  isKeyframe: boolean;
  isTracked: boolean;
  isCurrent: boolean;
  annotationId?: string;
  dimensions?: Dimensions3D;
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

  const [isOpen, setIsOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [trackAnnotations, setTrackAnnotations] = useState<any[]>([]);

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
  // - If no pinned track is set yet, pin it
  // - If it belongs to current pinned track, update class info
  // - If it belongs to a different track, do NOT auto-overwrite pinned session so user can Merge or Switch
  useEffect(() => {
    if (selectedAnnotation?.track_id) {
      if (!pinnedTrackId) {
        setPinnedTrackId(selectedAnnotation.track_id);
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
  }, [selectedAnnotation?.track_id, selectedAnnotation?.class_id, pinnedTrackId]);

  const activeTrackId = pinnedTrackId || selectedAnnotation?.track_id || null;

  const closeTimeline = useCallback(() => {
    setIsOpen(false);
    setPinnedTrackId(null);
  }, []);

  const switchTrack = useCallback((newTrackId: string) => {
    setPinnedTrackId(newTrackId);
    setIsOpen(true);
  }, []);

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

  useEffect(() => {
    if (activeTrackId) {
      fetchTrackAnnotations(activeTrackId);
    } else {
      setTrackAnnotations([]);
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

  // 7. Add current or specified candidate annotation into this track
  const addToTrack = useCallback(
    async (targetAnnId?: string) => {
      const annId = targetAnnId || candidateToLink?.id;
      if (!annId || !activeTrackId) return false;

      try {
        await annotation3DApi.update(annId, { track_id: activeTrackId });
        updateAnnotation(annId, { track_id: activeTrackId });
        // Refresh track annotations
        await fetchTrackAnnotations(activeTrackId);
        return true;
      } catch (err) {
        console.error('[useTrackTimeline] Failed to add annotation to track:', err);
        return false;
      }
    },
    [candidateToLink?.id, activeTrackId, updateAnnotation, fetchTrackAnnotations]
  );

  // 8. Detach / split annotation from current track (Error correction)
  const detachFromTrack = useCallback(
    async (targetAnnId?: string, mode: 'untrack' | 'split' = 'untrack') => {
      const annId =
        targetAnnId ||
        (selectedAnnotation?.track_id === activeTrackId
          ? selectedAnnotation.id
          : frameIndexToAnn.get(currentFrameIndex)?.id);

      if (!annId || !activeTrackId) return { success: false };

      try {
        let newTrackId: string | null = null;
        if (mode === 'split') {
          newTrackId =
            typeof crypto !== 'undefined' && crypto.randomUUID
              ? crypto.randomUUID()
              : `trk-${Date.now().toString(36)}`;
        }

        await annotation3DApi.update(annId, { track_id: newTrackId });
        updateAnnotation(annId, { track_id: newTrackId ?? undefined });

        // Refresh track annotations
        await fetchTrackAnnotations(activeTrackId);
        return { success: true, mode, newTrackId: newTrackId || undefined };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to detach annotation from track:', err);
        return { success: false };
      }
    },
    [
      selectedAnnotation,
      activeTrackId,
      frameIndexToAnn,
      currentFrameIndex,
      updateAnnotation,
      fetchTrackAnnotations,
    ]
  );

  // 9. Merge another track (sourceTrackId) into current activeTrackId (Target Precedence)
  const mergeWithTrack = useCallback(
    async (sourceTrackId: string) => {
      if (!activeTrackId || !sourceTrackId || activeTrackId === sourceTrackId || !task?.id) {
        return { success: false, mergedCount: 0, conflictCount: 0 };
      }

      setIsLoading(true);
      try {
        // Fetch all annotations for sourceTrackId
        const sourceList = await annotation3DApi.list(task.id, undefined, sourceTrackId);

        // Build lookup of frame_ids that already exist in activeTrack
        const activeFrameIdSet = new Set<string>();
        trackAnnotations.forEach((ann) => {
          if (ann.frame_id) {
            activeFrameIdSet.add(ann.frame_id);
          }
        });

        const bulkPayload: Array<{ id: string; track_id: string | null }> = [];
        let mergedCount = 0;
        let conflictCount = 0;

        (sourceList || []).forEach((ann) => {
          if (activeFrameIdSet.has(ann.frame_id)) {
            // Collision: Main track already has an annotation on this frame.
            // Main track takes precedence:
            // Do NOT change this box! Keep its original track_id intact so it can be merged with other tracks later.
            conflictCount++;
          } else {
            // No conflict: merge seamlessly into activeTrack
            mergedCount++;
            bulkPayload.push({
              id: ann.id,
              track_id: activeTrackId,
            });
          }
        });

        // Handle candidate annotation in current frame if also part of sourceTrack
        if (
          candidateToLink &&
          candidateToLink.track_id === sourceTrackId &&
          !bulkPayload.some((b) => b.id === candidateToLink.id)
        ) {
          if (activeFrameIdSet.has(candidateToLink.frame_id)) {
            conflictCount++;
          } else {
            mergedCount++;
            bulkPayload.push({
              id: candidateToLink.id,
              track_id: activeTrackId,
            });
          }
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
          sourceTrackId,
        };
      } catch (err) {
        console.error('[useTrackTimeline] Failed to merge tracks:', err);
        return { success: false, mergedCount: 0, conflictCount: 0 };
      } finally {
        setIsLoading(false);
      }
    },
    [activeTrackId, task?.id, trackAnnotations, candidateToLink, updateAnnotation, fetchTrackAnnotations]
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
    isCurrentFrameTracked,
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
    refreshTrack: () => activeTrackId && fetchTrackAnnotations(activeTrackId),
  };
}
