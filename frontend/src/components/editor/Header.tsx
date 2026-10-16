import React from 'react';
import { createPortal } from 'react-dom';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  taskApi,
  sceneApi,
  annotation2DApi,
  annotation3DApi,
  annotation4DApi,
  annotationApi,
  workflowApi,
} from '@/api/client';
import { useEditorStore } from '@/store/editorStore';
import { useAnnotation4DStore } from '@/store/annotation4DStore';
import { useAnnotation2DStore } from '@/store/annotation2DStore';
import { useTrackStore } from '@/store/trackStore';
import { BRAND } from '@/config/branding';
import type { ViewMode, AnnotationModeTab } from './types';
import type { Task, Taxonomy } from '@/types';

export interface HeaderProps {
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  annotationModeTab: AnnotationModeTab;
  setAnnotationModeTab: (mode: AnnotationModeTab) => void;
  availableModes: { fusion_3d: boolean; '2d_only': boolean };
  onOpenQACompleteModal: () => void;
  // Auto-save status
  isAutoSaving?: boolean;
  lastSavedAt?: Date | null;
  autoSaveError?: string | null;
  // Submission modal callbacks (state managed by parent)
  onShowSubmissionModal: (show: boolean) => void;
  onSetNextTask: (task: Task | null) => void;
  onSetLoadingNextTask: (loading: boolean) => void;
  // Taxonomy selection
  linkedTaxonomies?: Taxonomy[];
  urlTaxonomyId?: string | null; // Taxonomy ID from URL for initial display
  taxonomyReady?: boolean; // Whether URL taxonomy has been applied to scene
  // Per-taxonomy effective status (overrides task.stage/status when taxonomy is selected)
  effectiveStage?: string;
  effectiveStatus?: string;
  effectiveRevisionCount?: number;
}

const PointSizeSlider: React.FC = () => {
  const lidarView = useEditorStore((s) => s.lidarView);
  const setLidarView = useEditorStore((s) => s.setLidarView);

  return (
    <div className="flex items-center gap-2 bg-dark rounded-lg p-0.5 border border-gray-700 mx-1">
      <span className="text-[10px] text-gray-400 px-1">Size:</span>
      <input
        type="range"
        min="0.5"
        max="5"
        step="0.1"
        value={(lidarView.pointSize || 0.01) * 100}
        onChange={(e) => setLidarView({ pointSize: Number(e.target.value) / 100 })}
        className="w-16 h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-purple-500"
        title={`Point Size: ${((lidarView.pointSize || 0.01) * 100).toFixed(1)}`}
      />
    </div>
  );
};

const PointCloudColorSelector: React.FC = () => {
  const lidarView = useEditorStore((s) => s.lidarView);
  const setLidarView = useEditorStore((s) => s.setLidarView);

  return (
    <div className="flex items-center gap-1 bg-dark rounded-lg p-0.5 border border-gray-700 mx-1">
      <span className="text-[10px] text-gray-400 px-1">Points:</span>
      <select
        value={lidarView.colorMode}
        onChange={(e) => setLidarView({ colorMode: e.target.value as any })}
        className="bg-transparent text-[10px] font-medium text-gray-200 focus:outline-none cursor-pointer"
      >
        <option value="height" className="bg-dark text-gray-200">Height</option>
        <option value="height_above_ground" className="bg-dark text-gray-200">Above Ground</option>
        <option value="intensity" className="bg-dark text-gray-200">Intensity</option>
        <option value="class" className="bg-dark text-gray-200">Class</option>
      </select>
    </div>
  );
};

const ColorModeSelector: React.FC = () => {
  const annotationColorMode = useEditorStore((s) => s.annotationColorMode);
  const setAnnotationColorMode = useEditorStore((s) => s.setAnnotationColorMode);
  const taxonomy = useEditorStore((s) => s.taxonomy);
  const activeAttributeForColor = useEditorStore((s) => s.activeAttributeForColor);
  const setActiveAttributeForColor = useEditorStore((s) => s.setActiveAttributeForColor);

  const uniqueAttributes = React.useMemo(() => {
    if (!taxonomy?.classes) return [];
    return Array.from(new Set(
      taxonomy.classes.flatMap(c => Object.keys(c.attributes || {}))
    )).sort();
  }, [taxonomy]);

  return (
    <div className="flex items-center gap-2 bg-dark rounded-lg p-0.5 border border-gray-700 mx-2">
       <div className="flex items-center gap-1 px-1">
          <span className="text-[10px] text-gray-400">Color:</span>
          <select
            value={annotationColorMode}
            onChange={(e) => setAnnotationColorMode(e.target.value as any)}
            className="bg-transparent text-[10px] font-medium text-gray-200 focus:outline-none cursor-pointer"
          >
            <option value="class" className="bg-dark text-gray-200">Class</option>
            <option value="attribute" className="bg-dark text-gray-200">Attribute</option>
            <option value="qa_status" className="bg-dark text-gray-200">QA Status</option>
          </select>
       </div>

       {annotationColorMode === 'attribute' && (
         <>
           <div className="w-px h-3 bg-gray-700" />
           <select
              value={activeAttributeForColor ?? ''}
              onChange={(e) => setActiveAttributeForColor(e.target.value || null)}
              className="bg-transparent text-[10px] font-medium text-gray-200 focus:outline-none max-w-[80px] cursor-pointer"
           >
              <option value="" className="bg-dark text-gray-400">Attribute...</option>
               {uniqueAttributes.map(attr => (
                 <option key={attr} value={attr} className="bg-dark text-gray-200">{attr}</option>
               ))}
           </select>
         </>
       )}
    </div>
  );
};

export const Header: React.FC<HeaderProps> = ({
  viewMode,
  setViewMode,
  annotationModeTab,
  setAnnotationModeTab,
  availableModes,
  onOpenQACompleteModal,
  isAutoSaving,
  lastSavedAt,
  autoSaveError,
  onShowSubmissionModal,
  onSetNextTask,
  onSetLoadingNextTask,
  linkedTaxonomies,
  urlTaxonomyId,
  taxonomyReady = true,
  effectiveStage,
  effectiveStatus,
  effectiveRevisionCount,
}) => {
  const { task, isSaving, hasUnsavedChanges, saveAnnotations, setAnnotations, frames, scene, annotations } = useEditorStore();
  // Also get 4D annotations to include in delete count
  const annotations4D = useAnnotation4DStore((s) => s.annotations4D);
  // Compute total annotation count (regular + 4D)
  const totalAnnotationCount = React.useMemo(() => {
    const regularCount = annotations.size;
    const count4D = Array.from(annotations4D.values()).filter(a => !a.is_deleted).length;
    return regularCount + count4D;
  }, [annotations, annotations4D]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = React.useState<boolean>(false);
  const [isMigrating, setIsMigrating] = React.useState(false);
  const [isMenuOpen, setIsMenuOpen] = React.useState(false);
  const [isChangingTaxonomy, setIsChangingTaxonomy] = React.useState(false);

  // Session timer with pause/resume — state persisted per task+taxonomy in localStorage
  const [isTimerRunning, setIsTimerRunning] = React.useState(false);
  const [showTimerHint, setShowTimerHint] = React.useState(false);
  const [elapsedSeconds, setElapsedSeconds] = React.useState(0);
  const [timerStartedAt, setTimerStartedAt] = React.useState<string | null>(null);
  const timerIntervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  // Refs so the save-on-switch effect reads current values without stale closures
  const isTimerRunningRef = React.useRef(false);
  const elapsedSecondsRef = React.useRef(0);
  isTimerRunningRef.current = isTimerRunning;
  elapsedSecondsRef.current = elapsedSeconds;
  const prevTaxonomyIdRef = React.useRef<string>('');

  const timerStorageKey = task?.id && scene?.selected_taxonomy_id
    ? `task_timer_${task.id}_${scene.selected_taxonomy_id}`
    : task?.id
      ? `task_timer_${task.id}`
      : null;

  const clearTimerInterval = () => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
  };

  const startTimerInterval = () => {
    clearTimerInterval();
    timerIntervalRef.current = setInterval(() => {
      setElapsedSeconds(prev => prev + 1);
    }, 1000);
  };

  // Save previous taxonomy's timer and restore the new one whenever task or taxonomy changes
  React.useEffect(() => {
    if (!task?.id) return;
    const currentTaxId = scene?.selected_taxonomy_id ?? '';
    const prevTaxId = prevTaxonomyIdRef.current;

    // If taxonomy changed, save the outgoing timer state first
    if (prevTaxId && prevTaxId !== currentTaxId) {
      const prevKey = `task_timer_${task.id}_${prevTaxId}`;
      const currentElapsed = elapsedSecondsRef.current;
      const currentRunning = isTimerRunningRef.current;
      clearTimerInterval();
      try {
        const existing = JSON.parse(localStorage.getItem(prevKey) || '{}');
        if (currentRunning) {
          setIsTimerRunning(false);
          const breaks: { pausedAt: string; resumedAt?: string }[] = existing.breaks ?? [];
          breaks.push({ pausedAt: new Date().toISOString() });
          localStorage.setItem(prevKey, JSON.stringify({
            ...existing,
            elapsed: currentElapsed,
            running: false,
            lastActivityAt: new Date().toISOString(),
            breaks,
          }));
          if (currentElapsed > 0) {
            taskApi.update(task.id, { total_time_seconds: currentElapsed } as any).catch(() => {});
          }
        } else {
          localStorage.setItem(prevKey, JSON.stringify({ ...existing, elapsed: currentElapsed, running: false }));
        }
      } catch {}
    }

    prevTaxonomyIdRef.current = currentTaxId;

    // Restore new taxonomy's timer state
    clearTimerInterval();
    const newKey = currentTaxId
      ? `task_timer_${task.id}_${currentTaxId}`
      : `task_timer_${task.id}`;
    try {
      const raw = localStorage.getItem(newKey);
      if (raw) {
        const { elapsed, running, startedAt } = JSON.parse(raw) as { elapsed: number; running: boolean; startedAt?: string };
        setElapsedSeconds(elapsed ?? 0);
        setTimerStartedAt(startedAt ?? null);
        if (running) {
          startTimerInterval();
          setIsTimerRunning(true);
        } else {
          setIsTimerRunning(false);
        }
      } else {
        setElapsedSeconds(0);
        setTimerStartedAt(null);
        setIsTimerRunning(false);
      }
    } catch {
      setElapsedSeconds(0);
      setTimerStartedAt(null);
      setIsTimerRunning(false);
    }
    return () => clearTimerInterval();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id, scene?.selected_taxonomy_id]);

  // Persist on every tick and on pause/resume — preserve breaks array
  React.useEffect(() => {
    if (!timerStorageKey) return;
    // Skip saving until the restore effect has applied its values. In React 18
    // Strict Mode the effect runs twice; if we save zeros on the first pass we
    // overwrite the real saved state before the second pass can read it.
    if (elapsedSeconds === 0 && !isTimerRunning && timerStartedAt === null) return;
    try {
      const existing = JSON.parse(localStorage.getItem(timerStorageKey) || '{}');
      localStorage.setItem(timerStorageKey, JSON.stringify({
        ...existing,
        elapsed: elapsedSeconds,
        running: isTimerRunning,
        startedAt: timerStartedAt,
      }));
    } catch {
      localStorage.setItem(timerStorageKey, JSON.stringify({ elapsed: elapsedSeconds, running: isTimerRunning, startedAt: timerStartedAt }));
    }
  }, [elapsedSeconds, isTimerRunning, timerStartedAt, timerStorageKey]);

  // Broadcast timer state to same-tab listeners (e.g. Image2DAnnotationView tool lock)
  React.useEffect(() => {
    if (!task?.id) return;
    window.dispatchEvent(new CustomEvent('timerStateChange', { detail: { running: isTimerRunning, taskId: task.id } }));
  }, [isTimerRunning, task?.id]);

  React.useEffect(() => {
    const handleTimerHint = (event: Event) => {
      const detail = (event as CustomEvent<{ active?: boolean }>).detail;
      setShowTimerHint(Boolean(detail?.active));
    };

    window.addEventListener('timerControlAttention', handleTimerHint);
    return () => window.removeEventListener('timerControlAttention', handleTimerHint);
  }, []);

  React.useEffect(() => {
    if (isTimerRunning) {
      setShowTimerHint(false);
    }
  }, [isTimerRunning]);

  // Sync elapsed time to backend (fire-and-forget, best-effort)
  const syncTimerToBackend = React.useCallback((seconds: number) => {
    if (!task?.id || seconds <= 0) return;
    taskApi.update(task.id, { total_time_seconds: seconds } as any).catch(() => {});
  }, [task?.id]);

  // Sync on unmount so navigating away saves the time
  React.useEffect(() => {
    return () => {
      if (task?.id) {
        const taxId = scene?.selected_taxonomy_id;
        const key = taxId ? `task_timer_${task.id}_${taxId}` : `task_timer_${task.id}`;
        const raw = localStorage.getItem(key);
        if (raw) {
          try {
            const { elapsed } = JSON.parse(raw) as { elapsed: number };
            if (elapsed > 0) taskApi.update(task.id, { total_time_seconds: elapsed } as any).catch(() => {});
          } catch {}
        }
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id, scene?.selected_taxonomy_id]);

  const handleToggleTimer = () => {
    if (isTimerRunning) {
      clearTimerInterval();
      setIsTimerRunning(false);
      // Record break start and sync to backend
      if (timerStorageKey) {
        try {
          const raw = localStorage.getItem(timerStorageKey);
          const existing = raw ? JSON.parse(raw) : {};
          const breaks: { pausedAt: string; resumedAt?: string }[] = existing.breaks ?? [];
          breaks.push({ pausedAt: new Date().toISOString() });
          localStorage.setItem(timerStorageKey, JSON.stringify({
            ...existing,
            elapsed: elapsedSeconds,
            running: false,
            lastActivityAt: new Date().toISOString(),
            breaks,
          }));
        } catch {}
      }
      syncTimerToBackend(elapsedSeconds);
    } else {
      // Record resume time on existing break
      if (timerStorageKey) {
        try {
          const raw = localStorage.getItem(timerStorageKey);
          const existing = raw ? JSON.parse(raw) : {};
          const breaks: { pausedAt: string; resumedAt?: string }[] = existing.breaks ?? [];
          if (breaks.length > 0 && !breaks[breaks.length - 1].resumedAt) {
            breaks[breaks.length - 1].resumedAt = new Date().toISOString();
          }
          localStorage.setItem(timerStorageKey, JSON.stringify({ ...existing, breaks }));
        } catch {}
      }
      if (!timerStartedAt) {
        setTimerStartedAt(new Date().toISOString());
      }
      startTimerInterval();
      setIsTimerRunning(true);
    }
  };

  const formatSessionTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  // ── Per-frame time tracking (keyed per task + taxonomy) ──────────────────
  const frameEnterTimeRef = React.useRef<number | null>(null);
  const frameIndexRef = React.useRef<number>(-1);
  const _frameIndexForTracking = useEditorStore((s) => s.currentFrameIndex);

  React.useEffect(() => {
    const idx = _frameIndexForTracking;

    const saveFrameTime = (frameIndex: number, enterTime: number) => {
      if (!task?.id || frameIndex < 0) return;
      const spent = Math.round((Date.now() - enterTime) / 1000);
      if (spent <= 0 || spent >= 3600) return;
      try {
        const taxId = scene?.selected_taxonomy_id;
        const key = taxId
          ? `task_frame_times_${task.id}_${taxId}`
          : `task_frame_times_${task.id}`;
        const raw = localStorage.getItem(key);
        const data: Record<number, { totalSeconds: number; visits: number }> = raw ? JSON.parse(raw) : {};
        const entry = data[frameIndex] ?? { totalSeconds: 0, visits: 0 };
        entry.totalSeconds += spent;
        entry.visits += 1;
        data[frameIndex] = entry;
        localStorage.setItem(key, JSON.stringify(data));
      } catch {}
    };

    if (!task?.id || !isTimerRunning) {
      // Timer stopped — record time for the current frame before resetting
      if (frameEnterTimeRef.current !== null) {
        saveFrameTime(frameIndexRef.current, frameEnterTimeRef.current);
      }
      frameEnterTimeRef.current = null;
      frameIndexRef.current = idx;
      return;
    }

    const now = Date.now();
    const prevIndex = frameIndexRef.current;

    // Frame changed — record time spent on previous frame
    if (prevIndex >= 0 && frameEnterTimeRef.current !== null) {
      saveFrameTime(prevIndex, frameEnterTimeRef.current);
    }

    frameEnterTimeRef.current = now;
    frameIndexRef.current = idx;
  }, [_frameIndexForTracking, task?.id, isTimerRunning, scene?.selected_taxonomy_id]);

  // Mutation to update scene's selected taxonomy
  const updateSceneTaxonomyMutation = useMutation({
    mutationFn: ({ sceneId, taxonomyId }: { sceneId: string; taxonomyId: string | null }) =>
      sceneApi.updateSelectedTaxonomy(sceneId, taxonomyId),
    onSuccess: (updatedScene: any) => {
      // Update scene in editor store
      useEditorStore.getState().setScene(updatedScene);
      // Clear annotations from store so fresh ones are loaded
      setAnnotations([]);
      // Invalidate scene query to refresh
      queryClient.invalidateQueries({ queryKey: ['scene', scene?.id] });
      queryClient.invalidateQueries({ queryKey: ['task-editor-context', task?.id] });
      // Also invalidate annotation queries so they reload with new taxonomy filter
      queryClient.invalidateQueries({ queryKey: ['annotations'] });
      queryClient.invalidateQueries({ queryKey: ['all-3d-annotations'] });
      setIsChangingTaxonomy(false);
    },
    onError: (err: Error) => {
      console.error('Failed to update scene taxonomy:', err);
      setIsChangingTaxonomy(false);
    },
  });

  const handleTaxonomyChange = (taxonomyId: string) => {
    if (!scene?.id || isChangingTaxonomy) return;
    const newTaxonomyId = taxonomyId || null;
    if (newTaxonomyId === scene.selected_taxonomy_id) return;

    // Check if the new taxonomy is a segmentation_3d taxonomy
    const newTaxonomy = linkedTaxonomies?.find(t => t.id === newTaxonomyId);
    if (newTaxonomy?.annotation_mode === 'segmentation_3d' && task?.id) {
      // Redirect to segmentation editor with the new taxonomy
      navigate(`/tasks/${task.id}/segmentation?taxonomy=${newTaxonomyId}`, { replace: true });
      return;
    }

    setIsChangingTaxonomy(true);
    updateSceneTaxonomyMutation.mutate({ sceneId: scene.id, taxonomyId: newTaxonomyId });
  };
  const [showDeleteConfirm, setShowDeleteConfirm] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const [showBackTimerWarning, setShowBackTimerWarning] = React.useState(false);

  const handleBackClick = () => {
    if (isTimerRunning) {
      setShowBackTimerWarning(true);
    } else {
      navigate(-1);
    }
  };

  React.useEffect(() => {
    if (!showBackTimerWarning) return;

    const handleWarningEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowBackTimerWarning(false);
      }
    };

    window.addEventListener('keydown', handleWarningEscape);
    return () => window.removeEventListener('keydown', handleWarningEscape);
  }, [showBackTimerWarning]);

  // Notify the editor so overlapping overlays (e.g. the cuboid hint bar) can hide
  // while this dialog is open — it lives in a blurred, z-trapped stacking context.
  React.useEffect(() => {
    window.dispatchEvent(new CustomEvent('editorLeaveDialogChange', { detail: { open: showBackTimerWarning } }));
  }, [showBackTimerWarning]);

  // Close menu when clicking outside
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    if (isMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isMenuOpen]);

  const handleDeleteAllAnnotations = async () => {
    console.log('[DeleteAll] handleDeleteAllAnnotations called, task:', task?.id);
    try {
      if (!task?.id) {
        console.log('[DeleteAll] No task ID, returning early');
        return;
      }

      console.log('[DeleteAll] Starting deletion for task:', task.id);
      // Delete all annotations from the task
      await Promise.all([
        // Delete all 2D annotations in one call
        annotation2DApi.deleteByTask(task.id).catch(() => null),
        // Delete all 3D annotations using bulk delete
        (async () => {
          const ann3d = await annotation3DApi.list(task.id).catch(() => []);
          // Only call bulk delete if there are annotations to delete
          if (ann3d.length > 0) {
            await annotation3DApi.deleteBulk(ann3d.map(a => a.id)).catch(() => null);
          }
        })(),
        // Delete all 4D annotations using bulk delete
        (async () => {
          const ann4d = await annotation4DApi.list(task.id).catch(() => []);
          console.log('[DeleteAll] Found', ann4d.length, '4D annotations to delete');
          if (ann4d.length > 0) {
            await annotation4DApi.deleteBulk(ann4d.map(a => a.id)).catch((e) => {
              console.error('[DeleteAll] Failed to delete 4D annotations:', e);
              return null;
            });
            console.log('[DeleteAll] 4D annotations deleted from server');
          }
        })(),
        // Delete legacy annotations with pagination
        (async () => {
          let allLegacy: any[] = [];
          let page = 1;
          let hasMore = true;
          while (hasMore) {
            const legacy = await annotationApi.list({ taskId: task.id, pageSize: 1000, page }).catch(() => []);
            allLegacy.push(...legacy);
            hasMore = legacy.length === 1000;
            page++;
          }
          // Only delete if there are annotations
          if (allLegacy.length > 0) {
            // Delete in batches of 50 to avoid overwhelming backend
            for (let i = 0; i < allLegacy.length; i += 50) {
              const batch = allLegacy.slice(i, i + 50);
              await Promise.all(batch.map(a => annotationApi.delete(a.id).catch(() => null)));
              if (i + 50 < allLegacy.length) {
                await new Promise(resolve => setTimeout(resolve, 100));
              }
            }
          }
        })()
      ]);

      console.log('[DeleteAll] Annotation deletion complete, clearing frontend state');
      // Clear all in-memory state immediately so the UI updates without a refresh.

      // 1. Clear editor (3D) annotations and tracks
      setAnnotations([]);
      useTrackStore.setState({ tracks: new Map() });

      // 2. Clear 2D annotations
      useAnnotation2DStore.getState().clearAnnotations();

      // 3. Clear 4D annotations
      useAnnotation4DStore.getState().clearAnnotations4D();

      // 4. Remove React Query caches that feed mergeAnnotationsFromServer so stale
      //    data isn't rehydrated when the component re-renders or frames change.
      queryClient.removeQueries({ queryKey: ['annotations', task.id] });
      queryClient.removeQueries({ queryKey: ['all-3d-annotations', task.id] });

      // Always reset task back to annotation stage and clear all revision/QA data.
      console.log('[DeleteAll] About to reset task:', task.id);
      try {
        // Get current taxonomy ID for per-taxonomy reset
        const currentTaxonomyId = scene?.selected_taxonomy_id;

        // Reset per-taxonomy workflow if a taxonomy is selected
        if (currentTaxonomyId) {
          console.log('[DeleteAll] Resetting per-taxonomy workflow for taxonomy:', currentTaxonomyId);
          await workflowApi.setStage(task.id, 'annotation', currentTaxonomyId, true);
        }

        console.log('[DeleteAll] Calling taskApi.update with stage: annotation, revision_count: 0');
        const updatedTask = await taskApi.update(task.id, { stage: 'annotation', revision_count: 0 } as any);
        console.log('[DeleteAll] API response:', updatedTask);
        console.log('[DeleteAll] Response revision_count:', updatedTask.revision_count, 'stage:', updatedTask.stage);
        useEditorStore.getState().setTask(updatedTask);
        console.log('[DeleteAll] After setTask, store task:', useEditorStore.getState().task?.revision_count);
        queryClient.invalidateQueries({ queryKey: ['task', task.id] });
        queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
        queryClient.invalidateQueries({ queryKey: ['tasks'] });
        queryClient.invalidateQueries({ queryKey: ['my-tasks'] });
        queryClient.invalidateQueries({ queryKey: ['dataset-tasks'] });
        // Invalidate per-taxonomy workflow info cache
        queryClient.invalidateQueries({ queryKey: ['workflow-info', task.id] });
        queryClient.invalidateQueries({ queryKey: ['workflow-info-2d', task.id] });
        // Optimistically patch the task in the dataset-detail cache so the R badge
        // disappears immediately when the user navigates back (no stale-data flash).
        const taskIdStr = String(task.id);
        const patchTaskInDetail = (old: any) => {
          if (!old) return old;
          return {
            ...old,
            scenes: old.scenes?.map((s: any) => ({
              ...s,
              tasks: s.tasks?.map((t: any) =>
                String(t.id) === taskIdStr ? { ...t, revision_count: 0 } : t
              ),
            })),
          };
        };
        if (scene?.dataset_id) {
          queryClient.setQueryData(['dataset-detail', scene.dataset_id], patchTaskInDetail);
        } else {
          // Fallback: patch all dataset-detail caches
          queryClient.getQueriesData<any>({ predicate: (q) => q.queryKey[0] === 'dataset-detail' })
            .forEach(([key]) => queryClient.setQueryData(key, patchTaskInDetail));
        }
        queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] === 'dataset-detail' });
      } catch (resetErr) {
        console.error('Failed to reset task stage after delete all:', resetErr);
      }

      setShowDeleteConfirm(false);
      setIsMenuOpen(false);
    } catch (err) {
      console.error('Failed to delete all annotations:', err);
      setShowDeleteConfirm(false);
      setIsMenuOpen(false);
    }
  };

  // Reset revision mode without deleting annotations
  const handleResetRevisionMode = async () => {
    console.log('[ResetRevisionMode] Called, task:', task?.id, 'stage:', task?.stage, 'revision_count:', task?.revision_count);
    if (!task?.id) return;
    try {
      console.log('[ResetRevisionMode] Calling API with stage: annotation, revision_count: 0');
      const updatedTask = await taskApi.update(task.id, { stage: 'annotation', revision_count: 0 } as any);
      console.log('[ResetRevisionMode] API response:', updatedTask);
      useEditorStore.getState().setTask(updatedTask);
      queryClient.invalidateQueries({ queryKey: ['task', task.id] });
      queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['my-tasks'] });
      queryClient.invalidateQueries({ queryKey: ['dataset-tasks'] });
      // Optimistically patch dataset-detail caches
      const taskIdStr = String(task.id);
      const patchTaskInDetail = (old: any) => {
        if (!old) return old;
        return {
          ...old,
          scenes: old.scenes?.map((s: any) => ({
            ...s,
            tasks: s.tasks?.map((t: any) =>
              String(t.id) === taskIdStr ? { ...t, revision_count: 0 } : t
            ),
          })),
        };
      };
      if (scene?.dataset_id) {
        queryClient.setQueryData(['dataset-detail', scene.dataset_id], patchTaskInDetail);
      } else {
        queryClient.getQueriesData<any>({ predicate: (q) => q.queryKey[0] === 'dataset-detail' })
          .forEach(([key]) => queryClient.setQueryData(key, patchTaskInDetail));
      }
      queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] === 'dataset-detail' });
      setIsMenuOpen(false);
    } catch (err) {
      console.error('Failed to reset revision mode:', err);
    }
  };

  // 4D annotation store
  const saveAnnotations4D = useAnnotation4DStore((s) => s.saveAnnotations4D);
  const migrateToAnnotations = useAnnotation4DStore((s) => s.migrateToAnnotations);
  const updateFrameDataWithLidarCoords = useAnnotation4DStore((s) => s.updateFrameDataWithLidarCoords);

  // Check if there are 4D annotations
  const has4DAnnotations = React.useMemo(() => {
    return Array.from(annotations4D.values()).some(a => !a.is_deleted);
  }, [annotations4D]);

  // Check if there are unsaved 4D annotations
  const hasUnsaved4DChanges = React.useMemo(() => {
    return Array.from(annotations4D.values()).some(a => a.is_new || a.is_dirty || a.is_deleted);
  }, [annotations4D]);

  const handleSave = async () => {
    setSaveError(null);
    setSaveSuccess(false);
    const result = await saveAnnotations();
    if (!result.success) {
      setSaveError(result.error || 'Failed to save');
    } else {
      // Refetch annotations to sync with backend after successful save
      await queryClient.invalidateQueries({ queryKey: ['annotations', task?.id] });
      setSaveSuccess(true);
      // Hide success message after 3 seconds
      setTimeout(() => setSaveSuccess(false), 3000);
    }
  };

  // Handle 4D Save & Migrate: Save 4D annotations, then migrate to 3D
  const handleSave4D = async () => {
    if (!task) return;

    setSaveError(null);
    setSaveSuccess(false);
    setIsMigrating(true);

    try {
      // Step 0: Compute LiDAR coordinates for each frame from world coordinates
      // This is required for migration - the backend expects per-frame LiDAR coords
      if (has4DAnnotations && frames.length > 0) {
        // Computing LiDAR coordinates for migration (logging removed for performance)

        // Convert frames to the format expected by the transform function
        const frameData = frames.map(f => ({
          id: f.id,
          ego_pose: f.ego_pose ? {
            position: f.ego_pose.position,
            rotation: f.ego_pose.rotation,
          } : undefined,
        }));

        // Get calibration data (ego_to_lidar)
        const egoToLidar = scene?.calibration?.ego_to_lidar;

        // Update frame_data with computed LiDAR coordinates
        updateFrameDataWithLidarCoords(frameData, egoToLidar);
      }

      // Step 1: Save any pending 4D annotation changes (now with correct LiDAR coords)
      if (hasUnsaved4DChanges || has4DAnnotations) {
        const saveResult = await saveAnnotations4D();
        if (!saveResult.success) {
          setSaveError(saveResult.error || 'Failed to save 4D annotations');
          setIsMigrating(false);
          return;
        }
      }

      // Step 2: Migrate 4D annotations to 3D (creates one annotation per frame)
      if (has4DAnnotations) {
        const migrateResult = await migrateToAnnotations(task.id);
        if (!migrateResult.success) {
          setSaveError(migrateResult.error || 'Failed to migrate to 3D');
          setIsMigrating(false);
          return;
        }

        // Step 3: Reload annotations from Annotation3D table to see migrated ones
        const taxonomyIdForReload = scene?.selected_taxonomy_id;
        const freshAnnotations = await annotation3DApi.list(task.id, undefined, undefined, taxonomyIdForReload || undefined);
        // Convert to the format expected by setAnnotations
        const formattedAnnotations = freshAnnotations.map((ann: any) => ({
          ...ann,
          id: ann.id.toString(),
          task_id: ann.task_id.toString(),
          frame_id: ann.frame_id.toString(),
          track_id: ann.track_id?.toString() || null,
        }));
        setAnnotations(formattedAnnotations);

        // Invalidate React Query caches
        queryClient.invalidateQueries({ queryKey: ['annotations-3d'] });
        queryClient.invalidateQueries({ queryKey: ['all-3d-annotations'] });
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Migration failed');
    } finally {
      setIsMigrating(false);
    }
  };

  const handleSubmit = async () => {
    if (!task) return;

    // In 4D mode, migrate first
    if (viewMode === '4d' && has4DAnnotations) {
      await handleSave4D();
    }

    // Sync current elapsed time to backend before submitting
    syncTimerToBackend(elapsedSeconds);

    // Save annotations first
    const saveResult = await saveAnnotations();
    if (!saveResult.success) {
      setSaveError(saveResult.error || 'Failed to save before submit');
      return;
    }

    try {
      // Handle different stages - use effective stage/status which is per-taxonomy if taxonomy is selected
      // Get current taxonomy_id from scene's selected_taxonomy_id
      const currentTaxonomyId = scene?.selected_taxonomy_id;
      const currentStage = effectiveStage ?? task.stage;
      const currentStatus = effectiveStatus ?? task.status;
      const currentRevisionCount = effectiveRevisionCount ?? task.revision_count ?? 0;

      if (currentStage === 'annotation') {
        // Check if this is revision mode (revision_count > 0)
        if (currentRevisionCount > 0) {
          // Revision mode: submit fixes for QA re-review
          await workflowApi.submitFixes(task.id, currentTaxonomyId);
        } else {
          // Normal annotation stage: submit for QA review
          // Try to start work if pending/assigned - ignore errors if already in progress
          if (currentStatus === 'pending' || currentStatus === 'assigned') {
            try {
              await workflowApi.startWork(task.id, currentTaxonomyId);
            } catch (startErr) {
              // Ignore error - task might already be in progress (e.g., another tab, race condition)
              console.log('[FusionEditorV2] startWork failed (may already be in progress):', startErr);
            }
          }
          await workflowApi.submitAnnotation(task.id, currentTaxonomyId);
        }

        // Invalidate task cache so reopening this task gets fresh data with updated stage
        queryClient.invalidateQueries({ queryKey: ['task', task.id] });
        queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
        queryClient.invalidateQueries({ queryKey: ['tasks'] });
        queryClient.invalidateQueries({ queryKey: ['my-tasks'] });
        // Invalidate per-taxonomy workflow info
        queryClient.invalidateQueries({ queryKey: ['workflow-info', task.id, currentTaxonomyId] });

        // Show submission modal and fetch next task (use parent's state)
        onSetLoadingNextTask(true);
        onShowSubmissionModal(true);

        try {
          const next = await taskApi.getNextAssignedTask(task.id);
          onSetNextTask(next);
        } catch (err) {
          console.error('Failed to fetch next task:', err);
          onSetNextTask(null);
        } finally {
          onSetLoadingNextTask(false);
        }
      } else if (currentStage === 'qa') {
        // QA stage: open modal for accept/reject
        onOpenQACompleteModal();
        return; // Don't continue, wait for modal action
      } else if (currentStage === 'customer_qa') {
        // Customer QA stage: open modal for accept/reject
        onOpenQACompleteModal();
        return; // Don't continue, wait for modal action
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to submit');
    }
  };

  const hasDirtyChanges = hasUnsavedChanges();

  return (
    <div className="absolute top-0 left-0 right-0 h-12 z-[60] bg-dark-panel/95 backdrop-blur-sm border-b border-gray-700">
      {/* Back-button timer warning dialog */}
      {showBackTimerWarning && (
        <div className="fixed inset-0 z-[200]">
          <button
            type="button"
            aria-label="Dismiss timer warning"
            onClick={() => setShowBackTimerWarning(false)}
            className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
          />
          <div className="absolute top-16 left-6 w-80 rounded-xl border border-orange-500/45 bg-slate-950 shadow-[0_24px_60px_rgba(0,0,0,0.6)] overflow-hidden">
            <div className="h-0.5 w-full bg-gradient-to-r from-orange-600/0 via-orange-500/90 to-orange-600/0" />
            <div className="p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-orange-500/35 bg-orange-500/12">
                  <svg className="w-4 h-4 text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <circle cx="12" cy="12" r="9" />
                    <path strokeLinecap="round" d="M12 7v5l3 3" />
                  </svg>
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-white leading-tight">Timer is running</p>
                  <p className="mt-1 text-xs leading-snug text-slate-300">Pause the timer before leaving so your work time is saved accurately.</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-1 gap-2">
                <button
                  onClick={() => { handleToggleTimer(); setShowBackTimerWarning(false); navigate(-1); }}
                  className="w-full rounded-lg bg-orange-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-orange-500"
                >
                  Pause &amp; Leave
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setShowBackTimerWarning(false); navigate(-1); }}
                    className="flex-1 rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800 hover:text-white"
                  >
                    Leave anyway
                  </button>
                  <button
                    onClick={() => setShowBackTimerWarning(false)}
                    className="flex-1 rounded-lg border border-slate-700 bg-transparent px-3 py-2 text-xs font-medium text-slate-400 transition-colors hover:border-slate-500 hover:text-white"
                  >
                    Stay
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="h-full flex items-center px-4">
        {/* Logo - Left */}
        <Link to="/" className="flex items-center mr-3">
          {BRAND.showLogo ? (
            <img src="/logo.svg?v=3" alt={BRAND.name} className="h-7 w-auto" />
          ) : (
            <span className="text-sm font-bold bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-500 bg-clip-text text-transparent whitespace-nowrap">
              {BRAND.name}
            </span>
          )}
        </Link>

        <button
          onClick={handleBackClick}
          className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-dark-hover mr-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
        </button>

        {/* Centered: Title + View Mode */}
        <div className="flex-1 flex items-center justify-center gap-4 overflow-x-auto min-w-0">
          <div className="flex flex-col items-center">
            <span className="text-sm font-bold bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-500 bg-clip-text text-transparent">
              {BRAND.name}
            </span>
            <span className="text-[10px] text-gray-500">Sensor Fusion Annotation Platform</span>
          </div>

          <div className="h-6 w-px bg-gray-700" />

          {/* View Mode Selector */}
          <div className="flex items-center bg-dark rounded-lg p-0.5">
            {(['3d', '4d', '2d'] as ViewMode[]).map((mode) => {
              // Determine if this view tab should be enabled based on currently selected annotation mode tab
              // 3D/Fusion mode enables: 3D, Fusion, 4D tabs
              // 2D Only mode enables: only 2D tab
              const is3DView = mode === '3d' || mode === 'fusion' || mode === '4d';
              const is2DView = mode === '2d';
              const isEnabledByModeTab = (is3DView && annotationModeTab === 'fusion_3d') || (is2DView && annotationModeTab === '2d_only');
              // Also check if the mode is available at all (has taxonomy linked)
              const isModeAvailable = (is3DView && availableModes.fusion_3d) || (is2DView && availableModes['2d_only']);
              const isEnabled = isEnabledByModeTab && isModeAvailable;

              return (
                <button
                  key={mode}
                  onClick={() => isEnabled && setViewMode(mode)}
                  disabled={!isEnabled}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    !isEnabled
                      ? 'text-gray-600 cursor-not-allowed opacity-50'
                      : viewMode === mode
                        ? mode === '4d' ? 'bg-purple-600 text-white' : 'bg-primary text-white'
                        : 'text-gray-400 hover:text-white'
                  }`}
                  title={
                    !isModeAvailable
                      ? `No ${is3DView ? '3D/Fusion' : '2D'} taxonomy linked to this dataset`
                      : !isEnabledByModeTab
                        ? `Switch to ${is3DView ? '3D/Fusion' : '2D Only'} mode to use this view`
                        : mode === '4d'
                          ? 'Stack multiple LiDAR scans for static object labeling'
                          : undefined
                  }
                >
                  {mode === 'fusion' ? 'FUSION' : mode.toUpperCase()}
                </button>
              );
            })}
          </div>

          <div className="h-6 w-px bg-gray-700" />

          {/* Annotation Mode Tab Selector */}
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-500 mr-1">Mode:</span>
            <div className="flex items-center bg-dark rounded-lg p-0.5">
              <button
                onClick={() => availableModes.fusion_3d && setAnnotationModeTab('fusion_3d')}
                disabled={!availableModes.fusion_3d}
                className={`px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${
                  !availableModes.fusion_3d
                    ? 'text-gray-600 cursor-not-allowed opacity-50'
                    : annotationModeTab === 'fusion_3d'
                      ? 'bg-cyan-600 text-white'
                      : 'text-gray-400 hover:text-white'
                }`}
                title={!availableModes.fusion_3d ? 'No 3D/Fusion taxonomy linked to this dataset' : '3D/Fusion/4D annotations - cuboids, tracking objects'}
              >
                3D/Fusion
              </button>
              <button
                onClick={() => availableModes['2d_only'] && setAnnotationModeTab('2d_only')}
                disabled={!availableModes['2d_only']}
                className={`px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${
                  !availableModes['2d_only']
                    ? 'text-gray-600 cursor-not-allowed opacity-50'
                    : annotationModeTab === '2d_only'
                      ? 'bg-orange-500 text-white'
                      : 'text-gray-400 hover:text-white'
                }`}
                title={!availableModes['2d_only'] ? 'No 2D-only taxonomy linked to this dataset' : '2D-only annotations - lanes, traffic signs, traffic lights'}
              >
                2D Only
              </button>
            </div>
          </div>

          <ColorModeSelector />
          {viewMode !== '2d' && <PointSizeSlider />}
          {viewMode !== '2d' && <PointCloudColorSelector />}

          {/* Taxonomy Selector - show when multiple taxonomies are linked */}
          {linkedTaxonomies && linkedTaxonomies.length > 1 && (
            <>
              <div className="h-6 w-px bg-gray-700" />
              <div className="flex items-center gap-1 bg-dark rounded-lg p-0.5 border border-gray-700">
                <span className="text-[10px] text-gray-400 px-1">Taxonomy:</span>
                <select
                  value={urlTaxonomyId || scene?.selected_taxonomy_id || ''}
                  onChange={(e) => handleTaxonomyChange(e.target.value)}
                  disabled={isChangingTaxonomy || !taxonomyReady}
                  className="bg-transparent text-[10px] font-medium text-gray-200 focus:outline-none cursor-pointer max-w-[260px] disabled:opacity-50"
                  title={(linkedTaxonomies.find(t => t.id === (urlTaxonomyId || scene?.selected_taxonomy_id))?.name ?? 'Switch taxonomy to view/edit different annotation sets')}
                >
                  {linkedTaxonomies.map((tax) => (
                    <option key={tax.id} value={tax.id} className="bg-dark text-gray-200">
                      {tax.name}
                    </option>
                  ))}
                </select>
                {(isChangingTaxonomy || !taxonomyReady) && (
                  <svg className="w-3 h-3 animate-spin text-gray-400" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
                  </svg>
                )}
              </div>
            </>
          )}

          {/* Single taxonomy display - show when only one taxonomy is linked */}
          {linkedTaxonomies && linkedTaxonomies.length === 1 && (
            <>
              <div className="h-6 w-px bg-gray-700" />
              <div className="flex items-center gap-1 bg-dark rounded-lg p-0.5 border border-gray-700">
                <span className="text-[10px] text-gray-400 px-1">Taxonomy:</span>
                <span className="text-[10px] font-medium text-gray-200 px-1 max-w-[260px] truncate" title={linkedTaxonomies[0].name}>
                  {linkedTaxonomies[0].name}
                </span>
              </div>
            </>
          )}
        </div>

        {/* Right - Task info & Save buttons */}
        <div className="flex items-center gap-2">
          {/* Session Timer */}
          <div
            data-tour="timer-control"
            className={`flex items-center gap-1.5 px-2 py-1 rounded hidden sm:flex transition-all duration-200 ${
              showTimerHint && !isTimerRunning
                ? 'bg-gray-800/88 border border-amber-400/55 animate-timerControlHint'
                : 'bg-gray-800/60 border border-gray-700/60'
            }`}
            title={task?.total_time_seconds ? `Session: ${formatSessionTime(elapsedSeconds)} · Total: ${formatSessionTime(task.total_time_seconds + elapsedSeconds)}` : `Time in this session`}
          >
            <svg className="w-3 h-3 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <circle cx="12" cy="12" r="9" />
              <path strokeLinecap="round" d="M12 7v5l3 3" />
            </svg>
            <span className={`text-xs font-mono tabular-nums ${isTimerRunning ? 'text-gray-300' : 'text-gray-500'}`}>
              {formatSessionTime(elapsedSeconds)}
            </span>
            <button
              data-tour="timer-toggle"
              onClick={handleToggleTimer}
              className={`ml-0.5 transition-colors ${showTimerHint && !isTimerRunning ? 'text-amber-300 hover:text-amber-200' : 'text-gray-400 hover:text-white'}`}
              title={isTimerRunning ? 'Pause timer' : 'Resume timer'}
            >
              {isTimerRunning ? (
                /* Pause icon */
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="5" y="4" width="4" height="16" rx="1" />
                  <rect x="15" y="4" width="4" height="16" rx="1" />
                </svg>
              ) : (
                /* Play icon */
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6 4l14 8-14 8V4z" />
                </svg>
              )}
            </button>
          </div>

          <div className="text-right mr-2 hidden sm:block">
            {/* Show only the concise scene name; the full task name (scene + dataset +
                taxonomy) is available on hover. max-width + truncate keeps a long name
                from compressing the logo, especially when side panels claim width. */}
            <h1
              className="text-white font-medium text-xs truncate max-w-[260px] ml-auto"
              title={task?.name || undefined}
            >
              {scene?.name ?? task?.name ?? 'Loading...'}
            </h1>
            {task && (
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                  (effectiveStage ?? task.stage) === 'annotation' ? 'bg-blue-500/20 text-blue-400' :
                  (effectiveStage ?? task.stage) === 'qa' ? 'bg-purple-500/20 text-purple-400' :
                  (effectiveStage ?? task.stage) === 'customer_qa' ? 'bg-orange-500/20 text-orange-400' :
                  (effectiveStage ?? task.stage) === 'accepted' ? 'bg-green-500/20 text-green-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {(effectiveStage ?? task.stage) === 'qa' ? 'QA' : (effectiveStage ?? task.stage) === 'customer_qa' ? 'CUSTOMER QA' : (effectiveStage ?? task.stage).toUpperCase()}
                </span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  (effectiveStatus ?? task.status) === 'assigned' ? 'bg-blue-500/20 text-blue-400' :
                  (effectiveStatus ?? task.status) === 'in_progress' ? 'bg-yellow-500/20 text-yellow-400' :
                  (effectiveStatus ?? task.status) === 'submitted' ? 'bg-purple-500/20 text-purple-400' :
                  (effectiveStatus ?? task.status) === 'accepted' ? 'bg-green-500/20 text-green-400' :
                  (effectiveStatus ?? task.status) === 'rejected' ? 'bg-red-500/20 text-red-400' :
                  'bg-gray-500/20 text-gray-400'
                }`}>
                  {(effectiveStatus ?? task.status).replace('_', ' ')}
                </span>
                {(effectiveRevisionCount ?? task.revision_count) > 0 && (effectiveStage ?? task.stage) !== 'customer_qa' && (effectiveStage ?? task.stage) !== 'accepted' && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">
                    ⚠ Revision #{effectiveRevisionCount ?? task.revision_count}
                  </span>
                )}
              </div>
            )}
          </div>

          {saveSuccess && (
            <span className="text-xs text-green-400">✓</span>
          )}
          {saveError && (
            <span className="text-xs text-red-400" title={saveError}>!</span>
          )}

          {/* Auto-save status indicator */}
          <div className="flex flex-col items-end text-xs" title={lastSavedAt ? `Last saved: ${lastSavedAt.toLocaleTimeString()}` : 'Not saved yet'}>
            {isAutoSaving ? (
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span className="text-amber-400 hidden sm:inline">Saving...</span>
              </div>
            ) : autoSaveError ? (
              <div className="flex items-center gap-1">
                <div className="w-2 h-2 rounded-full bg-red-400" />
                <span className="text-red-400 hidden sm:inline" title={autoSaveError}>Error</span>
              </div>
            ) : lastSavedAt ? (
              <div className="flex flex-col items-end">
                <div className="flex items-center gap-1">
                  <div className="w-2 h-2 rounded-full bg-green-400" />
                  <span className="text-green-400 hidden sm:inline">Auto-saved</span>
                </div>
                <span className="text-[10px] text-gray-500 hidden sm:inline">{lastSavedAt.toLocaleTimeString()}</span>
              </div>
            ) : null}
          </div>

          {/* 4D Mode: Show Save & Migrate button */}
          {viewMode === '4d' ? (
            <>
              <button
                onClick={handleSave4D}
                disabled={isMigrating || (!hasUnsaved4DChanges && !has4DAnnotations)}
                className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                  (hasUnsaved4DChanges || has4DAnnotations)
                    ? 'bg-purple-600 text-white hover:bg-purple-500'
                    : 'text-gray-300 hover:bg-dark-hover'
                } disabled:opacity-50`}
                title="Save 4D annotations and migrate to 3D annotations for each frame"
              >
                {isMigrating ? 'Migrating...' : hasUnsaved4DChanges ? 'Save*' : 'Migrate'}
              </button>
            </>
          ) : (
            /* Regular mode: Standard Save button */
            <button
              onClick={handleSave}
              disabled={isSaving || !hasDirtyChanges}
              className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                hasDirtyChanges
                  ? 'bg-amber-600 text-white hover:bg-amber-500'
                  : 'text-gray-300 hover:bg-dark-hover'
              } disabled:opacity-50`}
            >
              {isSaving ? 'Saving...' : hasDirtyChanges ? 'Save*' : 'Save'}
            </button>
          )}

          <button
            onClick={handleSubmit}
            className="px-3 py-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700 text-xs disabled:opacity-50"
            disabled={!task || isSaving || isMigrating || ((effectiveStage ?? task?.stage) === 'annotation' && annotations.size === 0)}
            title={
              (effectiveStage ?? task?.stage) === 'annotation' && annotations.size === 0
                ? 'No annotations to submit - draw at least one annotation first'
                : (effectiveStage ?? task?.stage) === 'annotation'
                  ? 'Submit for QA review'
                  : (effectiveStage ?? task?.stage) === 'qa'
                    ? 'Complete QA review'
                    : 'Submit task'
            }
          >
            {(effectiveStage ?? task?.stage) === 'qa' || (effectiveStage ?? task?.stage) === 'customer_qa' ? 'Complete QA' : 'Submit'}
          </button>

          {/* Menu Button */}
          <div ref={menuRef} className="relative">
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className="p-2 rounded border border-gray-600 text-gray-300 hover:text-white hover:border-gray-500 hover:bg-dark-hover transition-colors flex items-center justify-center"
              title="More options"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                <circle cx="12" cy="5" r="1.5" fill="currentColor" />
                <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                <circle cx="12" cy="19" r="1.5" fill="currentColor" />
              </svg>
            </button>

            {/* Dropdown Menu */}
            {isMenuOpen && (
              <div className="absolute right-0 mt-1 bg-gray-800 border border-gray-600 rounded-lg shadow-2xl z-[100] min-w-[220px]">
                {/* Reset Revision Mode - only show when in revision mode */}
                {task && effectiveStage === 'annotation' && (effectiveRevisionCount ?? task.revision_count ?? 0) > 0 && (
                  <button
                    onClick={handleResetRevisionMode}
                    className="w-full px-4 py-3 text-left text-sm text-yellow-400 hover:bg-gray-700 hover:text-yellow-300 transition-colors flex items-center gap-2 border-b border-gray-700"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Reset Revision Mode
                  </button>
                )}
                <button
                  onClick={() => {
                    setShowDeleteConfirm(true);
                    setIsMenuOpen(false);
                  }}
                  className="w-full px-4 py-3 text-left text-sm text-red-400 hover:bg-gray-700 hover:text-red-300 transition-colors flex items-center gap-2 rounded-lg"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Delete All Annotations
                </button>
              </div>
            )}
          </div>

          {/* Delete Confirmation Dialog — portal to escape CSS transform stacking context */}
          {showDeleteConfirm && createPortal(
            <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[9999]">
              <div className="bg-gray-800 border border-gray-600 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
                <h3 className="text-lg font-bold text-white mb-2 flex items-center gap-2">
                  <svg className="w-5 h-5 text-red-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  Delete All Annotations?
                </h3>
                <p className="text-sm text-gray-300 mb-6">
                  This will permanently delete all{' '}
                  <span className="text-white font-semibold">{totalAnnotationCount}</span>{' '}
                  annotation{totalAnnotationCount !== 1 ? 's' : ''} from this task. This action cannot be undone.
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowDeleteConfirm(false)}
                    className="px-4 py-2 rounded-lg text-sm text-gray-300 bg-gray-700/50 hover:bg-gray-700 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleDeleteAllAnnotations}
                    className="px-4 py-2 rounded-lg text-sm bg-red-600 text-white hover:bg-red-700 transition-colors font-medium"
                  >
                    Delete All
                  </button>
                </div>
              </div>
            </div>
          , document.body)}

        </div>
      </div>
    </div>
  );
};
