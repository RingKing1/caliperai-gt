import React, { useEffect, useRef } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { useQAStore } from '@/store/qaStore';
import { useTrackStore } from '@/store/trackStore';
import { annotation3DApi } from '@/api/client';
import { pickAnnotations, sortByDistance } from '@/utils/annotationOrder';
import { showTransientHint } from '@/utils/transientHint';

export interface UseEditorHotkeysOptions {
  effectiveQAMode: boolean;
  timerRunningRef: React.MutableRefObject<boolean>;
  lockedAnnotationIdsRef: React.MutableRefObject<Set<string>>;
  showShortcutsHelp: boolean;
  setShowShortcutsHelp: React.Dispatch<React.SetStateAction<boolean>>;
  showOrthoViews: boolean;
  activeOrthoView: 'top' | 'side' | 'front' | null;
  setClickedLidarPoint: (point: { x: number; y: number; z: number } | null) => void;
  setVisibleCamerasForSelection: (cams: string[]) => void;
}

export const useEditorHotkeys = ({
  effectiveQAMode,
  timerRunningRef,
  lockedAnnotationIdsRef,
  showShortcutsHelp,
  setShowShortcutsHelp,
  showOrthoViews,
  activeOrthoView,
  setClickedLidarPoint,
  setVisibleCamerasForSelection,
}: UseEditorHotkeysOptions) => {
  // Multi-digit class hotkey selection: accumulate digits across keystrokes so
  // e.g. pressing '1' then '2' within 600ms selects class 12 (matches 2D editor).
  // Round-robin bookkeeping for the N / Shift+V navigation. `startRef` holds the
  // first box of the current cycle so we can tell when the user has wrapped
  // around; `notifiedRef` keeps the "all confirmed" hint to once per cycle.
  const cycleStartRef = useRef<string | null>(null);
  const lastCycleFrameRef = useRef<string | null>(null);
  const cycleNotifiedRef = useRef(false);

  const pendingDigitRef = useRef<string>('');
  const pendingDigitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timerHintTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }

      const store = useEditorStore.getState();
      const qaStore = useQAStore.getState();

      // Tool activation is gated by the work timer: when the timer is paused,
      // annotation tools must stay locked even via keyboard shortcuts — mirroring
      // the tool-palette button guard (timerLocked). Returns true if blocked.
      const blockedByTimer = (): boolean => {
        if (timerRunningRef.current) return false;
        // Draw attention to the timer control so the user knows to start it.
        window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: true } }));
        if (timerHintTimeoutRef.current) clearTimeout(timerHintTimeoutRef.current);
        timerHintTimeoutRef.current = setTimeout(
          () => window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: false } })),
          4000,
        );
        return true;
      };

      // Ctrl+S to save
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        store.saveAnnotations();
        return;
      }

      // Ctrl+Z to undo
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        store.undo();
        return;
      }

      // Ctrl+Shift+Z or Ctrl+Y to redo
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
        e.preventDefault();
        store.redo();
        return;
      }

      // Helper to get selected cuboid annotation
      const getSelectedCuboid = () => {
        const selectedIds = store.selection.selectedAnnotationIds;
        if (selectedIds.length !== 1) return null;
        const annotation = store.annotations.get(selectedIds[0]);
        if (!annotation || annotation.type !== 'cuboid') return null;
        // Block if annotation is locked (QA-approved in revision mode)
        if (lockedAnnotationIdsRef.current.has(annotation.id)) return null;
        return annotation;
      };

      // Helper to update cuboid data
      const updateCuboidData = (
        annotation: any,
        dataUpdates: Partial<{
          center: { x: number; y: number; z: number };
          dimensions: { length: number; width: number; height: number };
          rotation: { yaw: number; pitch: number; roll: number };
        }>,
      ) => {
        const currentData = annotation.data as {
          center: { x: number; y: number; z: number };
          dimensions: { length: number; width: number; height: number };
          rotation: { yaw: number; pitch: number; roll: number };
        };
        store.updateAnnotation(annotation.id, {
          data: {
            ...currentData,
            ...dataUpdates,
            center: dataUpdates.center ? { ...currentData.center, ...dataUpdates.center } : currentData.center,
            dimensions: dataUpdates.dimensions ? { ...currentData.dimensions, ...dataUpdates.dimensions } : currentData.dimensions,
            rotation: dataUpdates.rotation ? { ...currentData.rotation, ...dataUpdates.rotation } : currentData.rotation,
          },
        });
      };

      // Rotation and dimension adjustment increments
      const rotationStep = e.shiftKey ? 1 : 5; // 1° fine, 5° normal (in degrees)
      const dimensionStep = e.shiftKey ? 0.01 : 0.1; // 0.01m fine, 0.1m normal

      const key = e.key.toLowerCase();

      // ---------------------------------------------------------------------
      // Unconfirmed-box navigation (N / Shift+N / Shift+V)
      // ---------------------------------------------------------------------
      const currentFrameId = store.frames[store.currentFrameIndex]?.id;

      /** Annotations visible in the current frame, honouring the list filters. */
      const getFramePool = (): string[] => {
        const visible = store.visibleAnnotationIds || [];
        const filtered = visible.filter((id) => {
          const ann = store.annotations.get(id);
          return !!ann && ann.frame_id === currentFrameId && !lockedAnnotationIdsRef.current.has(id);
        });
        if (filtered.length > 0) return filtered;

        // List hidden or filters not published yet: fall back to every box in frame.
        const fallback: string[] = [];
        store.annotations.forEach((ann, annId) => {
          if (ann.frame_id === currentFrameId && !lockedAnnotationIdsRef.current.has(annId)) {
            fallback.push(annId);
          }
        });
        return fallback;
      };

      const selectAndReveal = (id: string) => {
        const s = useEditorStore.getState();
        s.selectAnnotation(id);
        s.requestScrollToAnnotation(id);
        // Re-centre without touching the zoom level.
        s.focusOnAnnotation(id, true);
      };

      /** Advance to the next unverified box in the current frame (circular). */
      const goNextUnverified = () => {
        const pool = getFramePool();
        if (pool.length === 0) {
          showTransientHint('本帧无标注');
          return;
        }

        const live = useEditorStore.getState();
        const anns = pickAnnotations(pool, live.annotations);
        const unverified = anns.filter((a) => !a.is_verified);
        // Nothing left to confirm -> keep cycling, but through every box.
        const poolForCycle = unverified.length > 0 ? unverified : anns;
        const ordered = sortByDistance(poolForCycle);

        const currentId = live.selection.selectedAnnotationIds[0];
        const idx = ordered.findIndex((a) => a.id === currentId);
        const next = idx >= 0 ? ordered[(idx + 1) % ordered.length] : ordered[0];

        // Announce once per cycle when the run wraps back to where it started.
        if (cycleStartRef.current === null) {
          cycleStartRef.current = next.id;
        } else if (next.id === cycleStartRef.current && !cycleNotifiedRef.current) {
          cycleNotifiedRef.current = true;
          showTransientHint(unverified.length > 0 ? '已浏览一遍，仍有未确认' : '本帧已全部确认');
        }

        selectAndReveal(next.id);
      };

      /** Jump to the first unverified box of a later frame (forward only). */
      const goNextFrameUnverified = async () => {
        const st = useEditorStore.getState();
        const taskId = st.task?.id;
        if (!taskId) return;

        const startIdx = st.currentFrameIndex + 1;
        if (startIdx >= st.frames.length) {
          showTransientHint('已是最后一帧');
          return;
        }

        const taxonomyId = st.scene?.selected_taxonomy_id || undefined;
        // Keyframe mode: step keyframe -> keyframe and let the server return only
        // keyframe rows. Non-keyframe frames are interpolated, so they carry
        // nothing an annotator would confirm here.
        const onlyKeyframes = st.keyframeSamplingEnabled === true;
        const keyframeStep = onlyKeyframes ? Math.max(1, st.keyframeInterval) : undefined;
        const keyframeOffset = onlyKeyframes ? st.keyframeStartFrame : undefined;
        const indexByFrameIndex = new Map<number, number>();
        const indexByFrameId = new Map<string, number>();
        st.frames.forEach((f, i) => {
          indexByFrameIndex.set(f.frame_index, i);
          indexByFrameId.set(f.id, i);
        });

        // Scan forward in chunks: the editor only keeps ~100 frames in memory,
        // so later frames have to be queried to know whether they still need work.
        const CHUNK = 100;
        for (let from = startIdx; from < st.frames.length; from += CHUNK) {
          const to = Math.min(from + CHUNK - 1, st.frames.length - 1);
          const frameStart = st.frames[from].frame_index;
          const frameEnd = st.frames[to].frame_index;

          let rows: Array<{ id: string; frame_id: string; is_verified?: boolean }> = [];
          try {
            rows = await annotation3DApi.list(
              taskId, undefined, undefined, taxonomyId,
              { frameStart, frameEnd, keyframeStep, keyframeOffset },
            );
          } catch (err) {
            console.error('[hotkeys] frame scan failed:', err);
            showTransientHint('查找失败，请检查网络');
            return;
          }

          // Candidates: unconfirmed rows that sit on a frame we are allowed to
          // land on (keyframe position in keyframe mode).
          const pending = rows.filter((r) => {
            if (r.is_verified === true) return false;
            if (!onlyKeyframes) return true;
            const idx = indexByFrameId.get(r.frame_id);
            return idx !== undefined && st.isKeyframeAt(idx);
          });
          if (pending.length === 0) continue;

          // Earliest frame in this chunk that still has unconfirmed boxes.
          const firstFrameId = pending.reduce((best, r) => {
            const bi = indexByFrameId.get(best) ?? Number.MAX_SAFE_INTEGER;
            const ri = indexByFrameId.get(r.frame_id) ?? Number.MAX_SAFE_INTEGER;
            return ri < bi ? r.frame_id : best;
          }, pending[0].frame_id);
          const target = pending
            .filter((r) => r.frame_id === firstFrameId)
            .sort((a, b) => a.id.localeCompare(b.id))[0];
          const targetIdx = indexByFrameId.get(firstFrameId);
          if (targetIdx === undefined) continue;

          cycleStartRef.current = null;
          cycleNotifiedRef.current = false;
          useEditorStore.getState().goToFrame(targetIdx);
          selectAndReveal(target.id);
          return;
        }

        showTransientHint(onlyKeyframes ? '后续关键帧没有未确认的框' : '后续帧没有未确认的框');
      };

      const refreshCycleOnFrameChange = () => {
        if (lastCycleFrameRef.current !== currentFrameId) {
          lastCycleFrameRef.current = currentFrameId;
          cycleStartRef.current = null;
          cycleNotifiedRef.current = false;
        }
      };
      refreshCycleOnFrameChange();

      // N = next unverified box in this frame
      if (key === 'n' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        goNextUnverified();
        return;
      }

      // Shift+N = first unverified box of the next frame(s)
      if (key === 'n' && e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        void goNextFrameUnverified();
        return;
      }


      // QA Mode shortcuts (1, 2, 3 for approve/reject/flag) - only for users with QA permission
      if (effectiveQAMode && qaStore.qaSession) {
        const selectedId = store.selection.selectedAnnotationIds[0];
        if (selectedId) {
          const annotation = store.annotations.get(selectedId);
          const currentFrameId = store.frames[store.currentFrameIndex]?.id;
          const classId = annotation?.class_id;

          switch (key) {
            case '1':
              e.preventDefault();
              qaStore.approveAnnotation(selectedId, currentFrameId, classId);
              return;
            case '2':
              e.preventDefault();
              qaStore.openRejectionModal(selectedId, currentFrameId, classId);
              return;
            case '3':
              e.preventDefault();
              qaStore.flagAnnotation(selectedId, undefined, currentFrameId, classId);
              return;
          }
        }
      }

      // Number keys for quick class selection (not in QA mode, no modifiers).
      // Multi-digit: press '1' then '2' within 600ms → select class 12.
      // Single digit: 1-9 selects classes 1-9; '0' alone selects class 10.
      if (!effectiveQAMode && !e.ctrlKey && !e.metaKey && /^[0-9]$/.test(e.key)) {
        e.preventDefault();
        const accumulated = pendingDigitRef.current + e.key;
        if (pendingDigitTimerRef.current) clearTimeout(pendingDigitTimerRef.current);

        const trySelectClass = (digits: string) => {
          const editor = useEditorStore.getState();
          const classes = editor.taxonomy?.classes ?? [];
          const idx = parseInt(digits, 10) - 1; // '1' → 0, '10' → 9, '12' → 11
          if (idx >= 0 && idx < classes.length) {
            editor.setActiveClass(classes[idx].id);
          }
          pendingDigitRef.current = '';
          editor.setPendingClassDigits('');
        };

        if (accumulated.length >= 2) {
          // Two digits typed — commit immediately.
          trySelectClass(accumulated);
        } else {
          // One digit so far — wait briefly for a possible second digit.
          pendingDigitRef.current = accumulated;
          store.setPendingClassDigits(accumulated);
          pendingDigitTimerRef.current = setTimeout(() => {
            // Special case: '0' alone → class 10.
            const digits = pendingDigitRef.current === '0' ? '10' : pendingDigitRef.current;
            trySelectClass(digits);
          }, 600);
        }
        return;
      }

      // Shift+V = confirm the current box (when still unconfirmed) and always
      // advance to the next unconfirmed box. Pressing it on an already confirmed
      // box simply moves on — it never un-confirms anything.
      if (key === 'v' && e.shiftKey && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          if (!annotation.is_verified) {
            store.updateAnnotation(annotation.id, { is_verified: true });
            useEditorStore.getState().saveAnnotations();
          }
          goNextUnverified();
          return;
        }
      }

      // V = toggle Accept (review-passed) flag on the selected cuboid
      if (key === 'v' && !e.shiftKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          store.updateAnnotation(annotation.id, { is_verified: !annotation.is_verified });
          useEditorStore.getState().saveAnnotations();
          return;
        }
      }

      // Rotation shortcuts (Q/E for yaw)
      if (key === 'q' || key === 'e') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as { rotation: { yaw: number; pitch: number; roll: number } };
          const direction = key === 'q' ? 1 : -1; // Q = rotate left (positive), E = rotate right (negative)
          const deltaRadians = (rotationStep * Math.PI) / 180;
          let newYaw = currentData.rotation.yaw + direction * deltaRadians;
          // Normalize to -π to π
          while (newYaw > Math.PI) newYaw -= 2 * Math.PI;
          while (newYaw < -Math.PI) newYaw += 2 * Math.PI;
          updateCuboidData(annotation, { rotation: { ...currentData.rotation, yaw: newYaw } });
        }
        return;
      }

      // Reset rotation (R)
      if (key === 'r' && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          updateCuboidData(annotation, { rotation: { yaw: 0, pitch: 0, roll: 0 } });
        }
        return;
      }

      // Determine active view mode:
      // 1. If an ortho panel is active, use it (top / front / side)
      // 2. Otherwise, check if main lidar canvas is in top view mode
      // 3. Otherwise default to 3d perspective view
      const currentView: 'top' | 'front' | 'side' | '3d' =
        showOrthoViews && activeOrthoView ? activeOrthoView : store.lidarView.isTopView ? 'top' : '3d';

      // Map view-relative screen axes to cuboid physical dimensions:
      // Vertical axis (W/S): Top -> width, Side -> height, Front -> height, 3D -> length
      // Horizontal axis (A/D): Top -> length, Side -> length, Front -> width, 3D -> width
      // Depth axis (Z/X): Top -> height, Side -> width, Front -> length, 3D -> height
      const verticalDim: 'length' | 'width' | 'height' =
        currentView === 'top' ? 'width' : currentView === 'side' || currentView === 'front' ? 'height' : 'length';

      const horizontalDim: 'length' | 'width' | 'height' =
        currentView === 'top' || currentView === 'side' ? 'length' : 'width';

      const depthDim: 'length' | 'width' | 'height' =
        currentView === 'top' ? 'height' : currentView === 'side' ? 'width' : currentView === 'front' ? 'length' : 'height';

      // Helper for symmetric adjustment (expands/contracts evenly from center on both sides)
      const adjustDimensionSymmetric = (
        annotation: any,
        dimType: 'length' | 'width' | 'height',
        delta: number,
      ) => {
        const currentData = annotation.data as {
          center: { x: number; y: number; z: number };
          dimensions: { length: number; width: number; height: number };
          rotation: { yaw: number; pitch: number; roll: number };
        };
        const currentDims = currentData.dimensions;
        const newDims = {
          ...currentDims,
          [dimType]: Math.max(0.1, currentDims[dimType] + delta),
        };
        updateCuboidData(annotation, { dimensions: newDims });
      };

      // Helper for single-edge adjustment:
      // Adjusts only the targeted edge while keeping the opposite edge strictly stationary.
      // delta > 0 means the box expands outward on that edge.
      // delta < 0 means the box shrinks inward on that edge.
      const adjustSingleEdge = (
        annotation: any,
        viewType: 'top' | 'side' | 'front',
        edge: 'top' | 'bottom' | 'left' | 'right',
        delta: number,
      ) => {
        const currentData = annotation.data as {
          center: { x: number; y: number; z: number };
          dimensions: { length: number; width: number; height: number };
          rotation: { yaw: number; pitch: number; roll: number };
        };
        const { length, width, height } = currentData.dimensions;
        const center = { ...currentData.center };
        const yaw = currentData.rotation?.yaw ?? 0;
        const cos = Math.cos(yaw);
        const sin = Math.sin(yaw);

        let newLength = length;
        let newWidth = width;
        let newHeight = height;

        // Local displacement of center along box-local axes
        let localDx = 0;
        let localDy = 0;
        let localDz = 0;

        if (viewType === 'top') {
          // Top view: horizontal is box X (length), vertical is box Y (width)
          if (edge === 'right') {
            newLength = Math.max(0.1, length + delta);
            localDx = (newLength - length) / 2;
          } else if (edge === 'left') {
            newLength = Math.max(0.1, length + delta);
            localDx = -(newLength - length) / 2;
          } else if (edge === 'top') {
            newWidth = Math.max(0.1, width + delta);
            localDy = (newWidth - width) / 2;
          } else if (edge === 'bottom') {
            newWidth = Math.max(0.1, width + delta);
            localDy = -(newWidth - width) / 2;
          }
        } else if (viewType === 'side') {
          // Side view: horizontal is box X (length), vertical is box Z (height)
          if (edge === 'right') {
            newLength = Math.max(0.1, length + delta);
            localDx = (newLength - length) / 2;
          } else if (edge === 'left') {
            newLength = Math.max(0.1, length + delta);
            localDx = -(newLength - length) / 2;
          } else if (edge === 'top') {
            newHeight = Math.max(0.1, height + delta);
            localDz = (newHeight - height) / 2;
          } else if (edge === 'bottom') {
            newHeight = Math.max(0.1, height + delta);
            localDz = -(newHeight - height) / 2;
          }
        } else if (viewType === 'front') {
          // Front view: looking along vehicle +X axis.
          // Screen right is vehicle -Y, screen left is vehicle +Y.
          // Screen up is vehicle +Z (height).
          if (edge === 'right') {
            newWidth = Math.max(0.1, width + delta);
            localDy = -(newWidth - width) / 2;
          } else if (edge === 'left') {
            newWidth = Math.max(0.1, width + delta);
            localDy = (newWidth - width) / 2;
          } else if (edge === 'top') {
            newHeight = Math.max(0.1, height + delta);
            localDz = (newHeight - height) / 2;
          } else if (edge === 'bottom') {
            newHeight = Math.max(0.1, height + delta);
            localDz = -(newHeight - height) / 2;
          }
        }

        // Rotate localDx, localDy to world coordinates based on yaw
        const worldDx = localDx * cos - localDy * sin;
        const worldDy = localDx * sin + localDy * cos;
        const worldDz = localDz;

        updateCuboidData(annotation, {
          dimensions: { length: newLength, width: newWidth, height: newHeight },
          center: {
            x: center.x + worldDx,
            y: center.y + worldDy,
            z: center.z + worldDz,
          },
        });
      };

      const { orthoEdgeState } = useEditorStore.getState();
      const isOrthoView = showOrthoViews && (currentView === 'top' || currentView === 'side' || currentView === 'front');
      const isHoveringOrtho = isOrthoView && (orthoEdgeState.activeView === currentView || !!orthoEdgeState.lockedEdge);
      const isCenterMode = e.altKey || !isHoveringOrtho;

      // Active vertical and horizontal edges:
      const activeVertical = orthoEdgeState.lockedEdge === 'top' || orthoEdgeState.lockedEdge === 'bottom'
        ? orthoEdgeState.lockedEdge
        : orthoEdgeState.verticalEdge;

      const activeHorizontal = orthoEdgeState.lockedEdge === 'left' || orthoEdgeState.lockedEdge === 'right'
        ? orthoEdgeState.lockedEdge
        : orthoEdgeState.horizontalEdge;

      // Dimension shortcuts - view-aware relative to active panel's coordinate system
      // W/S = Vertical axis of current view (W: move active edge UP, S: move active edge DOWN)
      if (key === 'w') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          if (isCenterMode || !isOrthoView) {
            adjustDimensionSymmetric(annotation, verticalDim, dimensionStep);
          } else {
            const targetEdge = activeVertical ?? 'top';
            const delta = targetEdge === 'top' ? dimensionStep : -dimensionStep;
            adjustSingleEdge(annotation, currentView, targetEdge, delta);
          }
          return;
        }
      }
      if (key === 's' && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          if (isCenterMode || !isOrthoView) {
            adjustDimensionSymmetric(annotation, verticalDim, -dimensionStep);
          } else {
            const targetEdge = activeVertical ?? 'bottom';
            const delta = targetEdge === 'top' ? -dimensionStep : dimensionStep;
            adjustSingleEdge(annotation, currentView, targetEdge, delta);
          }
          return;
        }
        // No annotation selected - fall through to tool switch
        if (blockedByTimer()) return;
        store.setActiveTool('brush3d');
        return;
      }

      // A/D = Horizontal axis of current view (D: move active edge RIGHT, A: move active edge LEFT)
      if (key === 'a') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          if (isCenterMode || !isOrthoView) {
            adjustDimensionSymmetric(annotation, horizontalDim, -dimensionStep);
          } else {
            const targetEdge = activeHorizontal ?? 'left';
            const delta = targetEdge === 'left' ? dimensionStep : -dimensionStep;
            adjustSingleEdge(annotation, currentView, targetEdge, delta);
          }
          return;
        }
      }
      if (key === 'd' && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          if (isCenterMode || !isOrthoView) {
            adjustDimensionSymmetric(annotation, horizontalDim, dimensionStep);
          } else {
            const targetEdge = activeHorizontal ?? 'right';
            const delta = targetEdge === 'right' ? dimensionStep : -dimensionStep;
            adjustSingleEdge(annotation, currentView, targetEdge, delta);
          }
          return;
        }
      }

      // Z/X = Depth (perpendicular) axis of current view (always symmetric)
      if (key === 'z' && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          adjustDimensionSymmetric(annotation, depthDim, dimensionStep);
          return;
        }
      }
      if (key === 'x') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          adjustDimensionSymmetric(annotation, depthDim, -dimensionStep);
          return;
        }
      }

      // Ctrl+D = Duplicate annotation
      if ((e.ctrlKey || e.metaKey) && key === 'd') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as { center: { x: number; y: number; z: number } };
          // Create duplicate offset by 1m in X
          const newAnnotation = store.createAnnotation({
            type: annotation.type,
            class_id: annotation.class_id,
            data: {
              ...annotation.data,
              center: {
                ...currentData.center,
                x: currentData.center.x + 1,
              },
            },
            attributes: { ...annotation.attributes },
          });
          store.selectAnnotation(newAnnotation.id);
        }
        return;
      }

      switch (key) {
        case 'h':
          // H = Help - toggle keyboard shortcuts dialog
          e.preventDefault();
          setShowShortcutsHelp(prev => !prev);
          break;
        case 'c':
          // C = Cuboid tool (disabled in QA mode)
          if (!effectiveQAMode && !blockedByTimer()) {
            store.setActiveTool('cuboid');
          }
          break;
        case 'l':
          if (!blockedByTimer()) store.setActiveTool('polyline');
          break;
        case 'p':
          if (!blockedByTimer()) store.setActiveTool('polygon');
          break;
        case 'f':
          if (e.altKey) {
            // Alt+F = toggle fisheye/pinhole projection
            e.preventDefault();
            store.toggleFisheyeProjection();
          } else if (e.shiftKey && effectiveQAMode) {
            // Shift+F for Flag Missing tool (QA mode only)
            store.setActiveTool('flag_missing');
          } else {
            // F = Forward frame
            e.preventDefault();
            store.nextFrame();
          }
          break;
        case 'b':
          // B = Backward frame
          e.preventDefault();
          store.prevFrame();
          break;
        case 't':
          // T = Track tool (matches the tool palette's advertised shortcut).
          // Shift+T = Toggle top view (kept on a T-based key for the "Top" mnemonic).
          e.preventDefault();
          if (e.shiftKey) {
            store.toggleTopView();
          } else if (!effectiveQAMode) {
            store.setActiveTool('track');
          }
          break;
        case 'g':
          // G = Go back to 3D perspective view (reset camera)
          e.preventDefault();
          store.resetCameraView();
          break;
        case 'arrowup':
        case 'arrowdown':
        case 'arrowleft':
        case 'arrowright': {
          const annotation = getSelectedCuboid();
          // If a box is selected (and not holding Alt to force frame step), nudge the box
          if (annotation && !e.altKey) {
            e.preventDefault();
            const moveStep = e.shiftKey ? 0.01 : 0.1; // 0.01m fine, 0.1m normal
            const currentData = annotation.data as { center: { x: number; y: number; z: number } };

            // Screen-space delta:
            // ArrowRight = +X (right), ArrowLeft = -X (left)
            // ArrowUp = +Y (up), ArrowDown = -Y (down)
            let screenDx = 0;
            let screenDy = 0;

            if (key === 'arrowright') screenDx = moveStep;
            else if (key === 'arrowleft') screenDx = -moveStep;
            else if (key === 'arrowup') screenDy = moveStep;
            else if (key === 'arrowdown') screenDy = -moveStep;

            // Map screen delta into box-local coordinates:
            // In Top view (BEV): box forward direction (+X) points right (+screenDx),
            //                   box left side (+Y) points up (+screenDy).
            // In Side view: box forward (+X) points right, height (+Z) points up.
            // In Front view: facing front, box right side (-Y) points right, height (+Z) points up.
            let localDx = 0;
            let localDy = 0;
            let localDz = 0;

            if (currentView === 'top') {
              localDx = screenDx;
              localDy = screenDy;
            } else if (currentView === 'side') {
              localDx = screenDx;
              localDz = screenDy;
            } else if (currentView === 'front') {
              localDy = -screenDx;
              localDz = screenDy;
            } else {
              // 3D Perspective view: forward/backward along heading, height by up/down
              localDx = screenDx;
              localDz = screenDy;
            }

            // Transform box-local delta to world / LiDAR coordinates using the box's heading yaw
            const yaw = (annotation.data as any)?.rotation?.yaw ?? 0;
            const cos = Math.cos(yaw);
            const sin = Math.sin(yaw);

            const worldDx = localDx * cos - localDy * sin;
            const worldDy = localDx * sin + localDy * cos;
            const worldDz = localDz;

            updateCuboidData(annotation, {
              center: {
                x: currentData.center.x + worldDx,
                y: currentData.center.y + worldDy,
                z: currentData.center.z + worldDz,
              },
            });
            break;
          }

          // When no annotation is selected (or holding Alt): left/right arrows navigate frames
          if (key === 'arrowleft' || key === 'arrowright') {
            e.preventDefault();
            if (e.shiftKey) {
              if (key === 'arrowright') {
                if (store.currentFrameIndex < store.frames.length - 1) {
                  store.goToFrame(store.currentFrameIndex + 1);
                }
              } else {
                if (store.currentFrameIndex > 0) {
                  store.goToFrame(store.currentFrameIndex - 1);
                }
              }
            } else {
              if (key === 'arrowright') {
                store.nextFrame();
              } else {
                store.prevFrame();
              }
            }
          }
          break;
        }
        case 'home':
          // Home = Go to first frame
          e.preventDefault();
          store.goToFrame(0);
          break;
        case 'end':
          // End = Go to last frame
          e.preventDefault();
          store.goToFrame(store.frames.length - 1);
          break;
        case 'delete':
        case 'backspace': {
          e.preventDefault();
          // Filter out locked (QA-approved) annotations from deletion
          const doomed = store.selection.selectedAnnotationIds
            .filter((id) => !lockedAnnotationIdsRef.current.has(id));
          if (doomed.length === 0) break;

          // Work out the successor BEFORE deleting: the list order is the
          // ordering the annotator sees, so "next box" means next row.
          const order = getFramePool();
          const anchor = doomed[0];
          const removed = new Set(doomed);
          const remaining = order.filter((id) => !removed.has(id));
          const anchorIdx = order.indexOf(anchor);
          const startIdx = anchorIdx >= 0 ? Math.min(anchorIdx, Math.max(remaining.length - 1, 0)) : 0;

          const liveAnns = useEditorStore.getState().annotations;
          const isUnverified = (id: string) => liveAnns.get(id)?.is_verified !== true;
          let nextId: string | null = null;
          if (remaining.length > 0) {
            // Prefer the next unconfirmed row, scanning forward then wrapping.
            const forward = remaining.slice(startIdx);
            const backward = remaining.slice(0, startIdx);
            nextId = forward.find(isUnverified) ?? backward.find(isUnverified) ?? null;
            // Everything is already confirmed -> just take the following row.
            if (!nextId) nextId = remaining[startIdx] ?? remaining[remaining.length - 1];
          }

          doomed.forEach((id) => store.deleteAnnotation(id));
          if (nextId) selectAndReveal(nextId);
          break;
        }
        case 'escape':
          e.preventDefault();
          if (showShortcutsHelp) {
            setShowShortcutsHelp(false);
          } else if (store.orthoEdgeState.lockedEdge) {
            store.setOrthoLockedEdge(null);
          } else if (store.isBoxPlacementActive) {
            // User is mid-drag placing a box — CuboidCreator's own Escape handler
            // cancels the drag and resets isBoxPlacementActive. Don't exit the
            // track tool so the annotator can immediately pick the next class.
            store.setBoxPlacementActive(false);
          } else {
            store.deselectAll();
            useTrackStore.getState().setActiveTrack(null); // Clear active track
            store.deactivateCameraView(); // Exit camera view mode
            store.setActiveTool('select'); // Reset to select tool
            setClickedLidarPoint(null); // Clear clicked point highlight
            setVisibleCamerasForSelection([]); // Restore default camera panel
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    effectiveQAMode,
    showShortcutsHelp,
    setShowShortcutsHelp,
    showOrthoViews,
    activeOrthoView,
    timerRunningRef,
    lockedAnnotationIdsRef,
    setClickedLidarPoint,
    setVisibleCamerasForSelection,
  ]);
};
