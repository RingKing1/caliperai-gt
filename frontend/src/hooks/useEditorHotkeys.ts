import React, { useEffect, useRef } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { useQAStore } from '@/store/qaStore';
import { useTrackStore } from '@/store/trackStore';

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

      // V = toggle Accept (review-passed) flag on the selected cuboid
      if (key === 'v') {
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

      // Dimension shortcuts - grow/shrink in POSITIVE direction only (shift center accordingly)
      // W/S = length (X axis) - grow towards +X
      if (key === 'w') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
            rotation: { yaw: number; pitch: number; roll: number };
          };
          const newLength = Math.max(0.1, currentData.dimensions.length + dimensionStep);
          // Shift center in +X direction by half the delta to grow towards +X only
          const centerShift = dimensionStep / 2;
          // Account for rotation: shift in local X direction
          const yaw = currentData.rotation.yaw;
          const shiftX = centerShift * Math.cos(yaw);
          const shiftY = centerShift * Math.sin(yaw);
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, length: newLength },
            center: { ...currentData.center, x: currentData.center.x + shiftX, y: currentData.center.y + shiftY },
          });
        }
        return;
      }
      if (key === 's' && !e.ctrlKey && !e.metaKey) {
        // S without modifier = decrease length (shrink from +X side)
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
            rotation: { yaw: number; pitch: number; roll: number };
          };
          const newLength = Math.max(0.1, currentData.dimensions.length - dimensionStep);
          // Shift center in -X direction by half the delta to shrink from +X side
          const centerShift = -dimensionStep / 2;
          const yaw = currentData.rotation.yaw;
          const shiftX = centerShift * Math.cos(yaw);
          const shiftY = centerShift * Math.sin(yaw);
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, length: newLength },
            center: { ...currentData.center, x: currentData.center.x + shiftX, y: currentData.center.y + shiftY },
          });
          return;
        }
        // No annotation selected - fall through to tool switch
        if (blockedByTimer()) return;
        store.setActiveTool('brush3d');
        return;
      }

      // A/D = width (Y axis) - grow towards +Y
      if (key === 'a') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
            rotation: { yaw: number; pitch: number; roll: number };
          };
          const newWidth = Math.max(0.1, currentData.dimensions.width + dimensionStep);
          // Shift center in +Y direction (local) by half the delta
          const centerShift = dimensionStep / 2;
          const yaw = currentData.rotation.yaw;
          // Local +Y is perpendicular to local +X: rotate 90 degrees
          const shiftX = -centerShift * Math.sin(yaw);
          const shiftY = centerShift * Math.cos(yaw);
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, width: newWidth },
            center: { ...currentData.center, x: currentData.center.x + shiftX, y: currentData.center.y + shiftY },
          });
        }
        return;
      }
      if (key === 'd') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
            rotation: { yaw: number; pitch: number; roll: number };
          };
          const newWidth = Math.max(0.1, currentData.dimensions.width - dimensionStep);
          // Shift center in -Y direction (local) by half the delta
          const centerShift = -dimensionStep / 2;
          const yaw = currentData.rotation.yaw;
          const shiftX = -centerShift * Math.sin(yaw);
          const shiftY = centerShift * Math.cos(yaw);
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, width: newWidth },
            center: { ...currentData.center, x: currentData.center.x + shiftX, y: currentData.center.y + shiftY },
          });
        }
        return;
      }

      // Z/X = height (Z axis) - grow towards +Z
      if (key === 'z' && !e.ctrlKey && !e.metaKey) {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
          };
          const newHeight = Math.max(0.1, currentData.dimensions.height + dimensionStep);
          // Shift center up by half the delta to grow upwards only
          const centerShift = dimensionStep / 2;
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, height: newHeight },
            center: { ...currentData.center, z: currentData.center.z + centerShift },
          });
        }
        return;
      }
      if (key === 'x') {
        const annotation = getSelectedCuboid();
        if (annotation) {
          e.preventDefault();
          const currentData = annotation.data as {
            center: { x: number; y: number; z: number };
            dimensions: { length: number; width: number; height: number };
          };
          const newHeight = Math.max(0.1, currentData.dimensions.height - dimensionStep);
          // Shift center down by half the delta to shrink from top
          const centerShift = -dimensionStep / 2;
          updateCuboidData(annotation, {
            dimensions: { ...currentData.dimensions, height: newHeight },
            center: { ...currentData.center, z: currentData.center.z + centerShift },
          });
        }
        return;
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
            // Keep Shift+Arrow in active ortho views for rotation controls handled by OrthographicViews
            if (showOrthoViews && activeOrthoView && e.shiftKey) {
              break;
            }

            e.preventDefault();
            const moveStep = e.shiftKey ? 0.01 : 0.1; // 0.01m fine, 0.1m normal
            const currentData = annotation.data as { center: { x: number; y: number; z: number } };

            // Determine active view mode:
            // 1. If an ortho panel is active, use it (top / front / side)
            // 2. Otherwise, check if main lidar canvas is in top view mode
            // 3. Otherwise default to 3d perspective view
            const currentView: 'top' | 'front' | 'side' | '3d' =
              showOrthoViews && activeOrthoView ? activeOrthoView : store.lidarView.isTopView ? 'top' : '3d';

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
        case 'backspace':
          e.preventDefault();
          // Filter out locked (QA-approved) annotations from deletion
          store.selection.selectedAnnotationIds
            .filter(id => !lockedAnnotationIdsRef.current.has(id))
            .forEach(id => store.deleteAnnotation(id));
          break;
        case 'escape':
          e.preventDefault();
          if (showShortcutsHelp) {
            setShowShortcutsHelp(false);
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
