import { useState, useRef, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import {
  taskApi,
  sceneApi,
  workflowApi,
  annotationApi,
  annotation2DApi,
  annotation3DApi,
  dataApi,
  type PointCloudResponse,
} from '@/api/client';
import { useEditorStore } from '@/store/editorStore';
import { useOnboardingStore } from '@/store/onboardingStore';
import { useLidarCacheStore } from '@/store/lidarCacheStore';
import { useImageCacheStore } from '@/store/imageCacheStore';
import { useAnnotation4DStore } from '@/store/annotation4DStore';
import { useAnnotation2DStore } from '@/store/annotation2DStore';
import type { PointCloudData } from '@/types';
import { normalizeSharedAttributes, normalizeTaxonomyConfig } from '@/utils/taxonomyUtils';
import type { ViewMode, AnnotationModeTab } from '@/components/editor/types';

export interface UseTaskDataLoaderOptions {
  taskId?: string;
  urlTaxonomyId: string | null;
  annotationModeTab: AnnotationModeTab;
  setAnnotationModeTab: (mode: AnnotationModeTab) => void;
  viewMode: ViewMode;
  setViewModeInternal: (mode: ViewMode) => void;
  cameraImageViewRef: React.MutableRefObject<boolean>;
}

export const useTaskDataLoader = ({
  taskId,
  urlTaxonomyId,
  annotationModeTab,
  setAnnotationModeTab,
  viewMode,
  setViewModeInternal,
  cameraImageViewRef,
}: UseTaskDataLoaderOptions) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const {
    setTask,
    setScene,
    setTaxonomy,
    setFrames,
    setAnnotations,
    mergeAnnotationsFromServer,
    deselectAll,
    currentFrame,
    currentFrameIndex,
  } = useEditorStore();

  // Aggregated editor bootstrap: task + scene + dataset + taxonomies in one
  // round trip instead of the previous task -> scene -> dataset -> taxonomy
  // request waterfall.
  const { data: editorContext, isLoading: loadingTask } = useQuery({
    queryKey: ['task-editor-context', taskId],
    queryFn: () => taskApi.getEditorContext(taskId!),
    enabled: !!taskId,
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const task = editorContext?.task;
  const scene = editorContext?.scene;
  const dataset = editorContext?.dataset;
  const linkedTaxonomies = editorContext?.taxonomies;
  const selectedTaxonomy = editorContext?.selected_taxonomy ?? undefined;
  const primaryTaxonomyForMode =
    editorContext?.primary_taxonomies?.[annotationModeTab] ?? null;

  // Backfill the standalone per-entity cache keys so other observers
  // (Sidebar, TaskDetailModal, cross-hook invalidations) reuse the prefetched
  // payload without issuing the old waterfall requests.
  useEffect(() => {
    if (!editorContext) return;
    const ctx = editorContext;
    queryClient.setQueryData(['task', ctx.task.id], ctx.task);
    queryClient.setQueryData(['scene', ctx.scene.id], ctx.scene);
    queryClient.setQueryData(['dataset', ctx.dataset.id], ctx.dataset);
    queryClient.setQueryData(['dataset-taxonomies', ctx.dataset.id], ctx.taxonomies);
    queryClient.setQueryData(
      ['dataset-primary-taxonomy', ctx.dataset.id, 'fusion_3d'],
      ctx.primary_taxonomies.fusion_3d ?? null,
    );
    queryClient.setQueryData(
      ['dataset-primary-taxonomy', ctx.dataset.id, '2d_only'],
      ctx.primary_taxonomies['2d_only'] ?? null,
    );
    if (ctx.selected_taxonomy) {
      queryClient.setQueryData(['taxonomy', ctx.selected_taxonomy.id], ctx.selected_taxonomy);
    }
    // task/scene previously had staleTime: 0 — mark the backfilled copies
    // stale (without refetching) to preserve that mount-refetch semantics.
    queryClient.invalidateQueries({ queryKey: ['task', ctx.task.id], refetchType: 'none' });
    queryClient.invalidateQueries({ queryKey: ['scene', ctx.scene.id], refetchType: 'none' });
  }, [editorContext, queryClient]);

  // Auto-set taxonomy from URL param mutation
  const autoSetTaxonomyMutation = useMutation({
    mutationFn: ({ sceneId, taxonomyId }: { sceneId: string; taxonomyId: string | null }) =>
      sceneApi.updateSelectedTaxonomy(sceneId, taxonomyId),
    onSuccess: (updatedScene: any) => {
      setScene(updatedScene);
      queryClient.invalidateQueries({ queryKey: ['scene', scene?.id] });
      queryClient.invalidateQueries({ queryKey: ['task-editor-context', taskId] });
      queryClient.invalidateQueries({ queryKey: ['annotations'] });
      queryClient.invalidateQueries({ queryKey: ['all-3d-annotations'] });
      setAnnotations([]);
    },
  });

  useEffect(() => {
    if (!scene?.id || !urlTaxonomyId) return;
    if (scene.selected_taxonomy_id === urlTaxonomyId) return;
    if (linkedTaxonomies === undefined) return;
    if (linkedTaxonomies.length > 0 && !linkedTaxonomies.some((t) => t.id === urlTaxonomyId)) {
      console.warn('[useTaskDataLoader] URL taxonomy not linked to dataset:', urlTaxonomyId);
      return;
    }
    autoSetTaxonomyMutation.mutate({ sceneId: scene.id, taxonomyId: urlTaxonomyId });
  }, [scene?.id, scene?.selected_taxonomy_id, urlTaxonomyId, linkedTaxonomies]);

  // Redirect to segmentation editor if active taxonomy is segmentation_3d
  useEffect(() => {
    if (!taskId || !linkedTaxonomies || linkedTaxonomies.length === 0) return;
    const activeTaxonomyId = urlTaxonomyId || scene?.selected_taxonomy_id;
    if (!activeTaxonomyId) return;

    const activeTaxonomy = linkedTaxonomies.find((t) => t.id === activeTaxonomyId);
    if (activeTaxonomy?.annotation_mode === 'segmentation_3d') {
      navigate(`/tasks/${taskId}/segmentation?taxonomy=${activeTaxonomyId}`, { replace: true });
    }
  }, [taskId, urlTaxonomyId, scene?.selected_taxonomy_id, linkedTaxonomies, navigate]);

  // Taxonomy workflow info
  const { data: taxonomyWorkflowInfo } = useQuery({
    queryKey: ['workflow-info', taskId, scene?.selected_taxonomy_id],
    queryFn: () => workflowApi.getInfo(taskId!, scene!.selected_taxonomy_id!),
    enabled: !!taskId && !!scene?.selected_taxonomy_id,
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const effectiveStage = taxonomyWorkflowInfo?.stage ?? task?.stage ?? 'annotation';
  const effectiveStatus = taxonomyWorkflowInfo?.status ?? task?.status ?? 'pending';
  const effectiveRevisionCount = taxonomyWorkflowInfo?.revision_count ?? task?.revision_count ?? 0;

  // Has LiDAR data check
  const hasLidarData = useMemo(() => {
    const hasLidarBase = Boolean(scene?.storage_paths?.lidar_base);
    const isVideoScene = (scene?.metadata as Record<string, unknown>)?.source === 'video_upload';
    return hasLidarBase && !isVideoScene;
  }, [scene]);

  // Available annotation modes
  const availableModes = useMemo(() => {
    const modes = { fusion_3d: false, '2d_only': false };
    if (!hasLidarData && scene) {
      modes['2d_only'] = true;
      return modes;
    }
    if (linkedTaxonomies && linkedTaxonomies.length > 0) {
      for (const tax of linkedTaxonomies) {
        if (tax.annotation_mode === 'fusion_3d') {
          modes.fusion_3d = true;
        } else if (tax.annotation_mode === '2d_only') {
          modes['2d_only'] = true;
        }
      }
    }
    if (!modes.fusion_3d && !modes['2d_only'] && dataset?.taxonomy?.classes && dataset.taxonomy.classes.length > 0) {
      modes.fusion_3d = true;
    }
    if (!modes.fusion_3d && !modes['2d_only'] && linkedTaxonomies !== undefined) {
      modes.fusion_3d = true;
    }
    return modes;
  }, [linkedTaxonomies, dataset, hasLidarData, scene]);

  // Tour trigger
  const { completedTours, isTourRunning, startTour } = useOnboardingStore();
  const tourStartedRef = useRef(false);

  useEffect(() => {
    if (tourStartedRef.current || isTourRunning) return;
    if (!availableModes.fusion_3d && !availableModes['2d_only']) return;

    const is2DOnly = availableModes['2d_only'] && !availableModes.fusion_3d;
    const tourId = is2DOnly ? 'editor_2d' : 'editor_3d';

    if (!completedTours.includes(tourId)) {
      tourStartedRef.current = true;
      setTimeout(() => {
        startTour(tourId);
      }, 1000);
    }
  }, [availableModes, completedTours, isTourRunning, startTour]);

  // Frames query
  const { data: framesData } = useQuery({
    queryKey: ['task-frames', taskId],
    queryFn: () => taskApi.getFrames(taskId!),
    enabled: !!taskId,
  });

  const selectedTaxonomyId = scene?.selected_taxonomy_id;
  const taxonomyReady = !urlTaxonomyId || (scene?.selected_taxonomy_id === urlTaxonomyId);

  // 3D summary query
  const { data: annotationSummary } = useQuery({
    queryKey: ['annotations-3d-summary', taskId, selectedTaxonomyId],
    queryFn: async () => {
      if (!taskId) return [];
      return annotation3DApi.summary(taskId, selectedTaxonomyId || undefined);
    },
    enabled: !!taskId && !!scene && taxonomyReady,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
  });

  // All 3D annotations
  const { data: allTaskAnnotations } = useQuery({
    queryKey: ['all-3d-annotations', taskId, selectedTaxonomyId],
    queryFn: async () => {
      if (!taskId) return [];
      return annotation3DApi.list(taskId, undefined, undefined, selectedTaxonomyId || undefined);
    },
    enabled: !!taskId && !!scene && taxonomyReady && !!annotationSummary,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
  });

  // Per-frame annotations
  const { data: annotations } = useQuery({
    queryKey: ['annotations', taskId, currentFrame?.id, selectedTaxonomyId],
    queryFn: async (): Promise<any[]> => {
      if (!taskId || !currentFrame?.id) return [];
      try {
        const [legacy, ann2d, ann3d] = await Promise.all([
          annotationApi.list({ taskId, frameId: currentFrame.id, taxonomyId: selectedTaxonomyId || undefined }).catch(() => []),
          annotation2DApi.list(taskId, currentFrame.id, undefined, undefined, selectedTaxonomyId || undefined).catch(() => []),
          annotation3DApi.list(taskId, currentFrame.id, undefined, selectedTaxonomyId || undefined).catch(() => []),
        ]);
        return [...legacy, ...ann2d, ...ann3d] as any[];
      } catch (e) {
        console.error('Failed to load annotations:', e);
        return [];
      }
    },
    enabled: !!taskId && !!currentFrame?.id && !!scene && taxonomyReady,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });

  // LiDAR file path
  const lidarFilePath = useMemo(() => {
    if (!scene?.storage_paths?.lidar_base || !currentFrame?.file_paths?.lidar) {
      return null;
    }
    const base = scene.storage_paths.lidar_base.replace(/\/$/, '');
    const filename = currentFrame.file_paths.lidar;
    return `${base}/${filename}`;
  }, [scene?.storage_paths?.lidar_base, currentFrame?.file_paths?.lidar]);

  const [displayedFrameIndex, setDisplayedFrameIndex] = useState(0);

  const getCachedLidar = useLidarCacheStore((s) => s.getCached);

  const { data: lidarData, isLoading: loadingLidar, isFetching: fetchingLidar } = useQuery({
    queryKey: ['lidar', lidarFilePath],
    queryFn: async () => {
      if (!lidarFilePath) return null;
      const cached = getCachedLidar(lidarFilePath);
      if (cached) return cached;
      return await dataApi.getLidarData(lidarFilePath);
    },
    enabled: !!lidarFilePath && availableModes.fusion_3d,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    placeholderData: (previousData: PointCloudResponse | null | undefined) => previousData,
  });

  useEffect(() => {
    if (availableModes.fusion_3d) {
      if (lidarData && !fetchingLidar) {
        setDisplayedFrameIndex(currentFrameIndex);
      }
    } else {
      setDisplayedFrameIndex(currentFrameIndex);
    }
  }, [lidarData, fetchingLidar, currentFrameIndex, availableModes.fusion_3d]);

  const lastValidPointCloudRef = useRef<PointCloudData | null>(null);

  const pointCloudData = useMemo<PointCloudData | undefined>(() => {
    if (!lidarData) {
      return lastValidPointCloudRef.current ?? undefined;
    }
    const positions = lidarData.positions instanceof Float32Array
      ? lidarData.positions
      : new Float32Array(lidarData.positions);
    const intensities = lidarData.intensities instanceof Float32Array
      ? lidarData.intensities
      : new Float32Array(lidarData.intensities);
    const newPointCloud = {
      positions,
      intensities,
      pointCount: lidarData.pointCount,
    };
    lastValidPointCloudRef.current = newPointCloud;
    return newPointCloud;
  }, [lidarData]);

  // Sync to store
  useEffect(() => { if (task) setTask(task); }, [task, setTask]);
  useEffect(() => { if (scene) setScene(scene); }, [scene, setScene]);
  useEffect(() => { if (framesData?.frames) setFrames(framesData.frames); }, [framesData, setFrames]);

  const previousTaskIdRef = useRef<string | null>(null);
  const previousTaxonomyIdRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (taskId && taskId !== previousTaskIdRef.current) {
      deselectAll();
      previousTaskIdRef.current = taskId;
    }
  }, [taskId, deselectAll]);

  // Sync taxonomy
  useEffect(() => {
    if (selectedTaxonomy?.classes && selectedTaxonomy.classes.length > 0) {
      const taxonomyConfig = {
        classes: selectedTaxonomy.classes || [],
        skeletons: selectedTaxonomy.skeletons || {},
        annotation_rules: selectedTaxonomy.annotation_rules || {
          min_points_polyline: 2,
          min_points_polygon: 3,
          allow_overlapping_boxes: false,
          require_track_id: false,
        },
        shared_attributes: selectedTaxonomy.shared_attributes || [],
      };
      setTaxonomy(taxonomyConfig);
      return;
    }

    if (primaryTaxonomyForMode?.classes && primaryTaxonomyForMode.classes.length > 0) {
      const taxonomyConfig = {
        classes: primaryTaxonomyForMode.classes || [],
        skeletons: primaryTaxonomyForMode.skeletons || {},
        annotation_rules: primaryTaxonomyForMode.annotation_rules || {
          min_points_polyline: 2,
          min_points_polygon: 3,
          allow_overlapping_boxes: false,
          require_track_id: false,
        },
        shared_attributes: primaryTaxonomyForMode.shared_attributes || [],
      };
      setTaxonomy(taxonomyConfig);
      return;
    }

    if (dataset?.taxonomy?.classes && dataset.taxonomy.classes.length > 0) {
      const embeddedShared = normalizeSharedAttributes(dataset.taxonomy.shared_attributes);
      const linkedShared = normalizeSharedAttributes(linkedTaxonomies?.[0]?.shared_attributes);
      const effectiveShared = embeddedShared.length > 0 ? embeddedShared : linkedShared;
      setTaxonomy({
        ...normalizeTaxonomyConfig(dataset.taxonomy),
        shared_attributes: effectiveShared,
      });
      return;
    }

    if (linkedTaxonomies && linkedTaxonomies.length > 0) {
      const firstLinkedTaxonomy = linkedTaxonomies[0];
      setTaxonomy({
        classes: firstLinkedTaxonomy.classes || [],
        skeletons: firstLinkedTaxonomy.skeletons || {},
        annotation_rules: firstLinkedTaxonomy.annotation_rules || {
          min_points_polyline: 2,
          min_points_polygon: 3,
          allow_overlapping_boxes: false,
          require_track_id: false,
        },
        shared_attributes: firstLinkedTaxonomy.shared_attributes || [],
      });
    }
  }, [dataset, linkedTaxonomies, primaryTaxonomyForMode, selectedTaxonomy, scene?.selected_taxonomy_id, annotationModeTab, setTaxonomy]);

  // Mode tab and view mode switching
  useEffect(() => {
    if (cameraImageViewRef.current) {
      cameraImageViewRef.current = false;
      return;
    }
    if (annotationModeTab === 'fusion_3d' && !availableModes.fusion_3d && availableModes['2d_only']) {
      setAnnotationModeTab('2d_only');
    } else if (annotationModeTab === '2d_only' && !availableModes['2d_only'] && availableModes.fusion_3d) {
      setAnnotationModeTab('fusion_3d');
    }

    const is3DView = viewMode === '3d' || viewMode === 'fusion' || viewMode === '4d';
    const is2DView = viewMode === '2d';

    if (annotationModeTab === 'fusion_3d' && is2DView) {
      setViewModeInternal('3d');
    } else if (annotationModeTab === '2d_only' && is3DView) {
      setViewModeInternal('2d');
    } else if (is3DView && !availableModes.fusion_3d && availableModes['2d_only']) {
      setViewModeInternal('2d');
    } else if (is2DView && !availableModes['2d_only'] && availableModes.fusion_3d) {
      setViewModeInternal('3d');
    }
  }, [availableModes, annotationModeTab, viewMode, setAnnotationModeTab, setViewModeInternal, cameraImageViewRef]);

  // Keyframe sampling settings persistence
  const keyframeSamplingEnabled = useEditorStore((st) => st.keyframeSamplingEnabled);
  const keyframeInterval = useEditorStore((st) => st.keyframeInterval);
  const keyframeStartFrame = useEditorStore((st) => st.keyframeStartFrame);
  const editorPrefsKey = taskId ? `editor_prefs_${taskId}` : null;
  const restoredFrameRef = useRef<string | null>(null);

  useEffect(() => {
    if (!editorPrefsKey) return;
    try {
      const raw = localStorage.getItem(editorPrefsKey);
      if (!raw) return;
      const prefs = JSON.parse(raw);
      const store = useEditorStore.getState();
      if (typeof prefs.keyframeSamplingEnabled === 'boolean') store.setKeyframeSamplingEnabled(prefs.keyframeSamplingEnabled);
      if (typeof prefs.keyframeInterval === 'number') store.setKeyframeInterval(prefs.keyframeInterval);
      if (typeof prefs.keyframeStartFrame === 'number') store.setKeyframeStartFrame(prefs.keyframeStartFrame);
    } catch { /* ignore */ }
  }, [editorPrefsKey]);

  useEffect(() => {
    if (!editorPrefsKey) return;
    const store = useEditorStore.getState();
    try {
      const raw = localStorage.getItem(editorPrefsKey);
      const prefs = raw ? JSON.parse(raw) : {};
      prefs.keyframeSamplingEnabled = store.keyframeSamplingEnabled;
      prefs.keyframeInterval = store.keyframeInterval;
      prefs.keyframeStartFrame = store.keyframeStartFrame;
      localStorage.setItem(editorPrefsKey, JSON.stringify(prefs));
    } catch { /* ignore */ }
  }, [editorPrefsKey, keyframeSamplingEnabled, keyframeInterval, keyframeStartFrame]);

  useEffect(() => {
    if (!editorPrefsKey || !framesData?.frames || framesData.frames.length === 0) return;
    if (restoredFrameRef.current === editorPrefsKey) return;
    restoredFrameRef.current = editorPrefsKey;
    try {
      const raw = localStorage.getItem(editorPrefsKey);
      const prefs = raw ? JSON.parse(raw) : {};
      const idx = Number(prefs.lastFrameIndex);
      if (Number.isFinite(idx) && idx >= 0 && idx < framesData.frames.length) {
        const t = setTimeout(() => useEditorStore.getState().goToFrame(idx), 50);
        return () => clearTimeout(t);
      }
    } catch { /* ignore */ }
  }, [editorPrefsKey, framesData]);

  const persistFrameIndex = useEditorStore((st) => st.currentFrameIndex);
  useEffect(() => {
    if (!editorPrefsKey) return;
    try {
      const raw = localStorage.getItem(editorPrefsKey);
      const prefs = raw ? JSON.parse(raw) : {};
      prefs.lastFrameIndex = persistFrameIndex;
      localStorage.setItem(editorPrefsKey, JSON.stringify(prefs));
    } catch { /* ignore */ }
  }, [editorPrefsKey, persistFrameIndex]);

  const lastSyncedFrameIdRef = useRef<string | null>(null);
  const lastSyncedTaxonomyIdRef = useRef<string | null | undefined>(undefined);

  // Sync all task annotations for backward interpolation
  useEffect(() => {
    if (!allTaskAnnotations?.length) return;
    if (lastSyncedTaxonomyIdRef.current === selectedTaxonomyId && lastSyncedFrameIdRef.current !== null) return;

    const filteredAnnotations = selectedTaxonomyId
      ? (allTaskAnnotations as any[]).filter((ann: any) => ann.taxonomy_id === selectedTaxonomyId)
      : (allTaskAnnotations as any[]);

    mergeAnnotationsFromServer(filteredAnnotations, '');
    lastSyncedTaxonomyIdRef.current = selectedTaxonomyId;
  }, [allTaskAnnotations, mergeAnnotationsFromServer, selectedTaxonomyId]);

  // Sync annotations when frame changes
  useEffect(() => {
    if (!annotations || !currentFrame?.id) return;
    if (lastSyncedFrameIdRef.current === currentFrame.id && lastSyncedTaxonomyIdRef.current === selectedTaxonomyId) return;

    const filteredAnnotations = selectedTaxonomyId
      ? (annotations as any[]).filter((ann: any) => ann.taxonomy_id === selectedTaxonomyId)
      : (annotations as any[]);

    mergeAnnotationsFromServer(filteredAnnotations, currentFrame.id);
    lastSyncedFrameIdRef.current = currentFrame.id;
    lastSyncedTaxonomyIdRef.current = selectedTaxonomyId;
  }, [annotations, currentFrame?.id, mergeAnnotationsFromServer, selectedTaxonomyId]);

  // Prefetching
  const startLidarPrefetch = useLidarCacheStore((s) => s.startPrefetch);
  const prefetchAroundFrame = useLidarCacheStore((s) => s.prefetchAround);
  const startImagePrefetch = useImageCacheStore((s) => s.startPrefetch);

  useEffect(() => {
    if (!scene || !framesData?.frames || framesData.frames.length === 0 || linkedTaxonomies === undefined) return;

    if (availableModes.fusion_3d) {
      const INITIAL_WINDOW = 10;
      const lo = Math.max(0, currentFrameIndex - INITIAL_WINDOW);
      const hi = Math.min(framesData.frames.length, currentFrameIndex + INITIAL_WINDOW + 1);
      const initialFrames = framesData.frames.slice(lo, hi);
      startLidarPrefetch(scene, initialFrames);
    }

    startImagePrefetch(scene, framesData.frames, currentFrameIndex);
  }, [scene, framesData?.frames, linkedTaxonomies, startLidarPrefetch, startImagePrefetch, availableModes.fusion_3d, currentFrameIndex]);

  useEffect(() => {
    if (!scene || !framesData?.frames || !availableModes.fusion_3d) return;
    prefetchAroundFrame(scene, framesData.frames, currentFrameIndex, 10);
  }, [currentFrameIndex, scene, framesData?.frames, availableModes.fusion_3d, prefetchAroundFrame]);

  // 4D Annotations
  const loadAnnotations4D = useAnnotation4DStore((s) => s.loadAnnotations4D);
  useEffect(() => {
    if (taskId) {
      loadAnnotations4D(taskId);
    }
  }, [taskId, loadAnnotations4D]);

  // Clear annotations on taxonomy change
  useEffect(() => {
    const prevTaxId = previousTaxonomyIdRef.current;
    const newTaxId = scene?.selected_taxonomy_id;

    if (prevTaxId !== undefined && prevTaxId !== newTaxId) {
      setAnnotations([]);
      useAnnotation2DStore.getState().clearAnnotations();
      lastSyncedFrameIdRef.current = null;
      lastSyncedTaxonomyIdRef.current = newTaxId;
      queryClient.invalidateQueries({ queryKey: ['annotations', taskId] });
      queryClient.invalidateQueries({ queryKey: ['all-3d-annotations', taskId] });
      queryClient.invalidateQueries({ queryKey: ['annotations-2d', taskId] });
    }

    previousTaxonomyIdRef.current = newTaxId;
  }, [scene?.selected_taxonomy_id, taskId, setAnnotations, queryClient]);

  // Notify backend that editor was opened
  useEffect(() => {
    if (task?.id) {
      workflowApi.onEditorOpen(task.id)
        .then((updatedWorkflow) => {
          if (updatedWorkflow.status !== task.status || updatedWorkflow.stage !== task.stage) {
            queryClient.invalidateQueries({ queryKey: ['task', task.id] });
            queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
          }
        })
        .catch((error) => {
          console.warn('[useTaskDataLoader] Failed to notify editor open:', error);
        });
    }
  }, [task?.id, task?.status, task?.stage, queryClient]);

  return {
    task,
    loadingTask,
    scene,
    dataset,
    linkedTaxonomies,
    selectedTaxonomy,
    effectiveStage,
    effectiveStatus,
    effectiveRevisionCount,
    hasLidarData,
    availableModes,
    taxonomyReady,
    displayedFrameIndex,
    pointCloudData,
    loadingLidar,
    fetchingLidar,
  };
};
