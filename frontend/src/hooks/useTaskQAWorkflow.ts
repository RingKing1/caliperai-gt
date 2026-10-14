import { useState, useRef, useMemo, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { qaApi, workflowApi } from '@/api/client';
import { useEditorStore } from '@/store/editorStore';
import { useAuthStore } from '@/store/authStore';
import { useQAStore, useIsQAMode } from '@/store/qaStore';
import { getDefaultCuboidDimensions } from '@/utils/cuboidDimensions';
import type { Task, Annotation, CuboidData } from '@/types';

export interface UseTaskQAWorkflowOptions {
  task?: Task;
  scene?: any;
  effectiveStage: string;
  effectiveStatus: string;
  setShowAnnotationList: (show: boolean) => void;
}

export const useTaskQAWorkflow = ({
  task,
  scene,
  effectiveStage,
  effectiveStatus,
  setShowAnnotationList,
}: UseTaskQAWorkflowOptions) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // QA Mode state
  const isQAMode = useIsQAMode();
  const {
    showRejectionModal,
    rejectionAnnotationId,
    setFrameNavigationCallbacks,
    flagMissingObject,
    startQASession,
    exitQAMode,
  } = useQAStore();

  const { canReviewQA } = useAuthStore();
  const userCanReviewQA = canReviewQA();
  const effectiveQAMode = isQAMode && userCanReviewQA;

  // QA Complete Modal
  const [showQACompleteModal, setShowQACompleteModal] = useState(false);

  // False negative flagging state
  const [falseNegativeLocation, setFalseNegativeLocation] = useState<{ x: number; y: number; z: number } | null>(null);
  const [showFalseNegativeModal, setShowFalseNegativeModal] = useState(false);

  // === Revision mode: fetch QA review data for locked annotations ===
  const isRevisionTask = !!(task && task.revision_count > 0 && task.stage === 'annotation');

  const { data: revisionReviews } = useQuery({
    queryKey: ['qa-reviews-for-revision', task?.id],
    queryFn: () => qaApi.getTaskReviews(task!.id),
    enabled: isRevisionTask,
    staleTime: 5 * 60 * 1000,
  });

  const latestRevisionReviewId = useMemo(() => {
    if (!revisionReviews?.length) return null;
    const sorted = [...revisionReviews].sort(
      (a, b) =>
        new Date(b.completed_at || b.created_at).getTime() -
        new Date(a.completed_at || a.created_at).getTime()
    );
    return sorted[0]?.id || null;
  }, [revisionReviews]);

  const { data: revisionAnnotationReviews } = useQuery({
    queryKey: ['qa-annotation-reviews-revision', latestRevisionReviewId],
    queryFn: () => qaApi.getAnnotationReviews(latestRevisionReviewId!),
    enabled: !!latestRevisionReviewId,
    staleTime: 5 * 60 * 1000,
  });

  const qaAnnotationReviews = useQAStore((s) => s.annotationReviews);

  // Set of locked (QA-approved) annotation IDs
  const lockedAnnotationIds = useMemo(() => {
    const set = new Set<string>();
    if (revisionAnnotationReviews) {
      for (const review of revisionAnnotationReviews) {
        if (review.verdict === 'approved') {
          set.add(review.annotation_id);
        }
      }
    }
    if (effectiveQAMode && qaAnnotationReviews.size > 0) {
      qaAnnotationReviews.forEach((review, annotationId) => {
        if (review.verdict === 'approved') {
          set.add(annotationId);
        }
      });
    }
    return set;
  }, [revisionAnnotationReviews, effectiveQAMode, qaAnnotationReviews]);

  const lockedAnnotationIdsRef = useRef(lockedAnnotationIds);
  lockedAnnotationIdsRef.current = lockedAnnotationIds;

  const setLockedAnnotationIds = useEditorStore((s) => s.setLockedAnnotationIds);
  useEffect(() => {
    setLockedAnnotationIds(lockedAnnotationIds);
  }, [lockedAnnotationIds, setLockedAnnotationIds]);

  // Auto-set annotation color mode to show QA verdicts for revision tasks
  const setAnnotationColorMode = useEditorStore((s) => s.setAnnotationColorMode);
  useEffect(() => {
    if (isRevisionTask && revisionAnnotationReviews && revisionAnnotationReviews.length > 0) {
      setAnnotationColorMode('qa_status');
    }
  }, [isRevisionTask, revisionAnnotationReviews, setAnnotationColorMode]);

  // Set QA navigation callbacks for auto-advance feature
  const nextFrame = useEditorStore((s) => s.nextFrame);
  const selectAnnotation = useEditorStore((s) => s.selectAnnotation);
  const goToFrame = useEditorStore((s) => s.goToFrame);
  const frames = useEditorStore((s) => s.frames);
  const focusOnAnnotation = useEditorStore((s) => s.focusOnAnnotation);
  const deselectAll = useEditorStore((s) => s.deselectAll);

  useEffect(() => {
    if (effectiveQAMode) {
      setFrameNavigationCallbacks(nextFrame, selectAnnotation);
    }
  }, [effectiveQAMode, nextFrame, selectAnnotation, setFrameNavigationCallbacks]);

  const handleJumpToAnnotation = useCallback(
    (annotationId: string, frameId?: string, _zoomLevel?: number) => {
      if (frameId && frames.length > 0) {
        const frameIndex = frames.findIndex((f) => f.id === frameId);
        if (frameIndex !== -1) {
          goToFrame(frameIndex);
          let attempts = 0;
          const maxAttempts = 30;
          const pollInterval = setInterval(() => {
            attempts++;
            const storeAnnotations = useEditorStore.getState().annotations;
            if (storeAnnotations.has(annotationId)) {
              clearInterval(pollInterval);
              selectAnnotation(annotationId);
              focusOnAnnotation(annotationId);
            } else if (attempts >= maxAttempts) {
              clearInterval(pollInterval);
              selectAnnotation(annotationId);
              focusOnAnnotation(annotationId);
              console.warn('[QA] Annotation not found after polling:', annotationId.slice(0, 8));
            }
          }, 100);
          return;
        } else {
          console.warn('[QA] Frame not found in frames list:', frameId);
        }
      }
      selectAnnotation(annotationId);
      focusOnAnnotation(annotationId);
    },
    [frames, goToFrame, selectAnnotation, focusOnAnnotation]
  );

  const handleSelectTrack = useCallback(
    (trackId: string) => {
      const storeAnnotations = useEditorStore.getState().annotations;
      let trackAnnotation: Annotation | undefined;
      for (const ann of storeAnnotations.values()) {
        if (ann.track_id === trackId || ann.id === trackId) {
          trackAnnotation = ann;
          break;
        }
      }
      if (trackAnnotation) {
        handleJumpToAnnotation(trackAnnotation.id, trackAnnotation.frame_id);
      }
    },
    [handleJumpToAnnotation]
  );

  const handleFlagMissingLocation = useCallback((location: { x: number; y: number; z: number }) => {
    setFalseNegativeLocation(location);
    setShowFalseNegativeModal(true);
  }, []);

  const handleFlagFalseNegative = useCallback(
    async (classId?: string, message?: string) => {
      if (!falseNegativeLocation) return;

      const { currentFrameIndex, frames: curFrames } = useEditorStore.getState();
      const currentFrame = curFrames[currentFrameIndex];
      if (!currentFrame) return;

      try {
        await flagMissingObject({
          frameId: currentFrame.id,
          location: falseNegativeLocation,
          suggestedClass: classId,
          message,
        });
        setShowFalseNegativeModal(false);
        setFalseNegativeLocation(null);
      } catch (error) {
        console.error('[QA] Failed to flag false negative:', error);
      }
    },
    [falseNegativeLocation, flagMissingObject]
  );

  const handleCreateAnnotationDirectly = useCallback(
    async (classId: string) => {
      if (!falseNegativeLocation) return;

      const { createAnnotation, activeClassId, taxonomy } = useEditorStore.getState();
      const finalClassId = classId || activeClassId || taxonomy?.classes[0]?.id;

      if (!finalClassId) {
        console.error('[QA] No class selected for new annotation');
        return;
      }

      const [length, width, height] = getDefaultCuboidDimensions(finalClassId, taxonomy);

      const defaultCuboid: CuboidData = {
        center: { x: falseNegativeLocation.x, y: falseNegativeLocation.y, z: falseNegativeLocation.z },
        dimensions: { length, width, height },
        rotation: { yaw: 0, pitch: 0, roll: 0 },
      };

      createAnnotation({
        type: 'cuboid',
        data: defaultCuboid,
        class_id: finalClassId,
        source: 'qa_correction',
      });

      setShowFalseNegativeModal(false);
      setFalseNegativeLocation(null);
    },
    [falseNegativeLocation]
  );

  const handleAcceptQA = useCallback(async () => {
    if (!task) return;

    const currentTaxonomyId = scene?.selected_taxonomy_id;
    const stageToCheck = effectiveStage ?? task.stage;
    const statusToCheck = effectiveStatus ?? task.status;

    if (statusToCheck === 'accepted' || (stageToCheck !== 'qa' && stageToCheck !== 'customer_qa')) {
      console.warn('Task is already processed or not in QA stage', { stage: stageToCheck, status: statusToCheck });
      setShowQACompleteModal(false);
      navigate('/');
      return;
    }

    try {
      if (stageToCheck === 'qa') {
        await workflowApi.completeQAReview(task.id, true, undefined, currentTaxonomyId);
      } else if (stageToCheck === 'customer_qa') {
        await workflowApi.completeCustomerReview(task.id, true, undefined, currentTaxonomyId);
      }

      setShowQACompleteModal(false);
      queryClient.invalidateQueries({ queryKey: ['task', task.id] });
      queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
      queryClient.invalidateQueries({ queryKey: ['taxonomy-workflow', task.id] });
      setTimeout(() => navigate('/'), 1000);
    } catch (err) {
      console.error('Failed to accept QA:', err);
      setShowQACompleteModal(false);
      alert('Failed to complete QA review. The task may have already been processed.');
      navigate('/');
    }
  }, [task, scene, queryClient, navigate, effectiveStage, effectiveStatus]);

  const handleRejectQA = useCallback(
    async (reason: string) => {
      if (!task) return;

      const currentTaxonomyId = scene?.selected_taxonomy_id;
      const stageToCheck = effectiveStage ?? task.stage;
      const statusToCheck = effectiveStatus ?? task.status;

      if (
        statusToCheck === 'accepted' ||
        statusToCheck === 'rejected' ||
        (stageToCheck !== 'qa' && stageToCheck !== 'customer_qa')
      ) {
        console.warn('Task is already processed or not in QA stage', { stage: stageToCheck, status: statusToCheck });
        setShowQACompleteModal(false);
        navigate('/');
        return;
      }

      try {
        if (stageToCheck === 'qa') {
          await workflowApi.completeQAReview(task.id, false, reason, currentTaxonomyId);
        } else if (stageToCheck === 'customer_qa') {
          await workflowApi.completeCustomerReview(task.id, false, reason, currentTaxonomyId);
        }

        setShowQACompleteModal(false);
        queryClient.invalidateQueries({ queryKey: ['task', task.id] });
      queryClient.invalidateQueries({ queryKey: ['task-editor-context', task.id] });
        queryClient.invalidateQueries({ queryKey: ['taxonomy-workflow', task.id] });
        setTimeout(() => navigate('/'), 1000);
      } catch (err) {
        console.error('Failed to reject QA:', err);
        setShowQACompleteModal(false);
        alert('Failed to reject QA review. The task may have already been processed.');
        navigate('/');
      }
    },
    [task, scene, queryClient, navigate, effectiveStage, effectiveStatus]
  );

  useEffect(() => {
    const stageToCheck = effectiveStage;

    if (task && (stageToCheck === 'qa' || stageToCheck === 'customer_qa') && !isQAMode && userCanReviewQA) {
      deselectAll();
      setShowAnnotationList(false);

      startQASession(task.id, 'suggest', stageToCheck)
        .then(() => {
          console.log('[useTaskQAWorkflow] QA session started successfully');
        })
        .catch((error) => {
          console.error('[useTaskQAWorkflow] Failed to auto-resume QA session:', error);
        });
    } else if (task && stageToCheck === 'annotation' && isQAMode) {
      exitQAMode();
      setShowAnnotationList(true);
    }
  }, [effectiveStage, task?.id, isQAMode, startQASession, userCanReviewQA, exitQAMode, deselectAll, setShowAnnotationList]);

  return {
    effectiveQAMode,
    showQACompleteModal,
    setShowQACompleteModal,
    showRejectionModal,
    rejectionAnnotationId,
    falseNegativeLocation,
    setFalseNegativeLocation,
    showFalseNegativeModal,
    setShowFalseNegativeModal,
    lockedAnnotationIdsRef,
    isRevisionTask,
    handleJumpToAnnotation,
    handleSelectTrack,
    handleFlagMissingLocation,
    handleFlagFalseNegative,
    handleCreateAnnotationDirectly,
    handleAcceptQA,
    handleRejectQA,
  };
};
