import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useEditorStore } from '@/store/editorStore';
import { useAutoSave } from '@/hooks/useAutoSave';
import { useCameraProjections } from '@/hooks/useCameraProjections';
import { useTaskQAWorkflow } from '@/hooks/useTaskQAWorkflow';
import { useTaskDataLoader } from '@/hooks/useTaskDataLoader';
import { useEditorHotkeys } from '@/hooks/useEditorHotkeys';

// Canvas & View Components
import { LidarCanvas, LidarCanvas4DNew } from '@/components/canvas/LidarCanvas';
import { ClipBoxControls } from '@/components/canvas/LidarCanvas/ClipBoxControls';
import { OrthographicViews } from '@/components/canvas/OrthographicViews';
import { OrthographicViews4D } from '@/components/canvas/OrthographicViews4D';
import {
  RejectionModal,
  AnnotationComments,
  TabbedQAPanel,
  FalseNegativeModal,
  QACompleteModal,
  QAFeedbackPanel,
} from '@/components/qa';
import { AnnotationListPanel } from '@/components/AnnotationListPanel';

// Modular Editor Components
import { ToolPalette, ClassPickerPanel } from '@/components/editor/ToolPalette';
import { CameraPanel } from '@/components/editor/CameraPanel';
import { CoordinateDisplay } from '@/components/editor/CoordinateDisplay';
import { Header } from '@/components/editor/Header';
import { Timeline } from '@/components/editor/Timeline';
import { FocusedCameraViews } from '@/components/editor/FocusedCameraViews';
import { FusionLabelingView } from '@/components/editor/FusionLabelingView';
import { TrackTimelineBar } from '@/components/editor/TrackTimelineBar';
import { TaskSubmissionModal } from '@/components/editor/TaskSubmissionModal';
import { ShortcutsHelpModal } from '@/components/editor/ShortcutsHelpModal';
import { CanvasOverlayControls } from '@/components/editor/CanvasOverlayControls';
import { CuboidPlacementHint } from '@/components/editor/CuboidPlacementHint';

// Types
import type { Task } from '@/types';
import type {
  ViewMode,
  AnnotationModeTab,
  OrthoViewType,
  AnnotationCapability,
} from '@/components/editor/types';

// =============================================================================
// MAIN EDITOR
// =============================================================================

export const FusionEditorV2: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const urlTaxonomyId = searchParams.get('taxonomy');

  const [viewMode, setViewModeInternal] = useState<ViewMode>('3d');
  const [annotationModeTab, setAnnotationModeTab] = useState<AnnotationModeTab>('fusion_3d');
  const cameraImageViewRef = useRef(false);

  const [showOrthoViews, setShowOrthoViews] = useState(false);
  const [orthoViewsWidth, setOrthoViewsWidth] = useState(480);
  const [activeOrthoView, setActiveOrthoView] = useState<OrthoViewType | null>(null);

  const [showAnnotationList, setShowAnnotationList] = useState(true);
  const [annotationPanelWidth, setAnnotationPanelWidth] = useState(280);

  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false);
  const [showSubmissionModal, setShowSubmissionModal] = useState(false);
  const [nextTask, setNextTask] = useState<Task | null>(null);
  const [isLoadingNextTask, setIsLoadingNextTask] = useState(false);

  const [stackedPointCloud4D, setStackedPointCloud4D] = useState<{
    positions: Float32Array;
    pointCount: number;
    origin?: [number, number, number];
  } | null>(null);

  const deselectAll = useEditorStore((s) => s.deselectAll);
  const selection = useEditorStore((s) => s.selection);
  const currentFrame = useEditorStore((s) => s.currentFrame);
  const activeTool = useEditorStore((s) => s.activeTool);
  const setActiveTool = useEditorStore((s) => s.setActiveTool);

  // 1. Task & Scene Data Loader Hook
  const {
    task,
    loadingTask,
    scene,
    linkedTaxonomies,
    effectiveStage,
    effectiveStatus,
    effectiveRevisionCount,
    availableModes,
    taxonomyReady,
    displayedFrameIndex,
    pointCloudData,
    loadingLidar,
    fetchingLidar,
  } = useTaskDataLoader({
    taskId,
    urlTaxonomyId,
    annotationModeTab,
    setAnnotationModeTab,
    viewMode,
    setViewModeInternal,
    cameraImageViewRef,
  });

  // 2. QA & Revision Workflow Hook
  const {
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
    handleJumpToAnnotation,
    handleSelectTrack,
    handleFlagMissingLocation,
    handleFlagFalseNegative,
    handleCreateAnnotationDirectly,
    handleAcceptQA,
    handleRejectQA,
  } = useTaskQAWorkflow({
    task,
    scene,
    effectiveStage,
    effectiveStatus,
    setShowAnnotationList,
  });

  // 3. Camera Projections & Visibility Hook
  const {
    setVisibleCamerasForSelection,
    clickedLidarPoint,
    setClickedLidarPoint,
    focusCamerasPanelHeight,
    setFocusCamerasPanelHeight,
    selectedCuboid,
    selectedClassColor,
    camerasToShow,
    isFullWidthCameraPanel,
    defaultCameraPanelHeight,
    getImageUrl,
    getOriginalImageUrl,
    handleEmptySpaceClick,
    handlePointCloudClick,
    openCameraImageView,
  } = useCameraProjections();

  // Auto-save annotations
  const { isSaving: isAutoSaving, lastSavedAt, lastError: autoSaveError } = useAutoSave({
    interval: 2000,
    enabled: true,
    autoRefresh: true,
    taskId,
    onSaveError: (error) => console.error('[AutoSave] Auto-save failed:', error),
  });

  // Wrapper for setViewMode that clears 3D selection when switching to 2D tab
  const setViewMode = useCallback((mode: ViewMode) => {
    if (mode === '2d') {
      deselectAll();
    }
    setViewModeInternal(mode);
  }, [deselectAll]);

  // Auto-show/hide ortho views based on selection
  useEffect(() => {
    setShowOrthoViews(selection.selectedAnnotationIds.length > 0);
  }, [selection.selectedAnnotationIds]);

  useEffect(() => {
    if (!showOrthoViews || selection.selectedAnnotationIds.length === 0 || viewMode === '2d') {
      setActiveOrthoView(null);
    }
  }, [showOrthoViews, selection.selectedAnnotationIds.length, viewMode]);

  // Submission navigation handlers
  const handleOpenNextTask = useCallback(() => {
    if (nextTask) {
      setShowSubmissionModal(false);
      window.location.href = `/tasks/${nextTask.id}`;
    }
  }, [nextTask]);

  const handleGoToTaskList = useCallback(() => {
    setShowSubmissionModal(false);
    navigate('/my-tasks');
  }, [navigate]);

  // Timer running state & tool reset
  const [timerRunning, setTimerRunning] = useState(false);
  const timerRunningRef = useRef(false);

  useEffect(() => {
    const apply = (running: boolean) => {
      timerRunningRef.current = running;
      setTimerRunning(running);
    };
    try {
      const raw = localStorage.getItem(`task_timer_${taskId}`);
      if (raw !== null) apply(JSON.parse(raw).running === true);
    } catch { /* ignore */ }
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ running: boolean; taskId: string }>).detail;
      if (detail?.taskId === taskId) apply(detail.running === true);
    };
    window.addEventListener('timerStateChange', handler);
    return () => window.removeEventListener('timerStateChange', handler);
  }, [taskId]);

  useEffect(() => {
    if (!timerRunning && activeTool !== 'select' && activeTool !== 'flag_missing') {
      setActiveTool('select');
    }
  }, [timerRunning, activeTool, setActiveTool]);

  // Keyboard shortcuts hook
  useEditorHotkeys({
    effectiveQAMode,
    timerRunningRef,
    lockedAnnotationIdsRef,
    showShortcutsHelp,
    setShowShortcutsHelp,
    showOrthoViews,
    activeOrthoView,
    setClickedLidarPoint,
    setVisibleCamerasForSelection,
  });

  const availableCapabilities: AnnotationCapability[] = [
    'bounding_box_3d', 'bounding_box_2d', 'semantic_segmentation', 'tracking', 'polygon', 'polyline'
  ];

  if (loadingTask) {
    return (
      <div className="h-screen bg-dark flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin w-12 h-12 border-4 border-primary border-t-transparent rounded-full mx-auto mb-4" />
          <div className="text-white">Loading annotation task...</div>
        </div>
      </div>
    );
  }

  const isRevisionPanelVisible =
    !effectiveQAMode &&
    task &&
    (effectiveRevisionCount ?? task.revision_count) > 0 &&
    effectiveStage === 'annotation' &&
    viewMode !== '2d';

  const getRightOffset = () => {
    if (viewMode === 'fusion') return 'right-1/2';
    if (showOrthoViews) return 'right-96';
    if (isRevisionPanelVisible) return 'right-80';
    return 'right-0';
  };

  const camerasPanelVisible = viewMode !== '2d' && camerasToShow.length > 0;
  const bottomOffsetPx = camerasPanelVisible ? (focusCamerasPanelHeight || defaultCameraPanelHeight) : 0;

  return (
    <div className="h-screen bg-dark overflow-hidden relative">
      {/* Header */}
      <Header
        viewMode={viewMode}
        setViewMode={setViewMode}
        annotationModeTab={annotationModeTab}
        setAnnotationModeTab={setAnnotationModeTab}
        availableModes={availableModes}
        onOpenQACompleteModal={() => setShowQACompleteModal(true)}
        isAutoSaving={isAutoSaving}
        lastSavedAt={lastSavedAt}
        autoSaveError={autoSaveError}
        onShowSubmissionModal={setShowSubmissionModal}
        onSetNextTask={setNextTask}
        onSetLoadingNextTask={setIsLoadingNextTask}
        linkedTaxonomies={linkedTaxonomies}
        urlTaxonomyId={urlTaxonomyId}
        taxonomyReady={taxonomyReady}
        effectiveStage={effectiveStage}
        effectiveStatus={effectiveStatus}
        effectiveRevisionCount={effectiveRevisionCount}
      />

      {/* Canvas Overlay Controls (BEV, Fisheye, Ground Plane, Shortcuts, Camera view indicator) */}
      <CanvasOverlayControls
        viewMode={viewMode}
        onOpenShortcutsHelp={() => setShowShortcutsHelp(true)}
        onOpenCameraImageView={openCameraImageView}
      />

      {/* Tour anchors */}
      <div
        data-tour="lidar-canvas"
        className="absolute pointer-events-none"
        style={{
          top: '80px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '200px',
          height: '100px',
          background: 'transparent',
        }}
      />
      <div
        data-tour="2d-canvas"
        className="absolute pointer-events-none"
        style={{
          top: '80px',
          right: '20%',
          width: '200px',
          height: '100px',
          background: 'transparent',
        }}
      />

      {/* Main 3D Canvas */}
      {viewMode !== '4d' && (
        <div
          className={`absolute top-12 left-0 transition-all duration-300 ${getRightOffset()} ${viewMode === '2d' ? 'hidden' : ''}`}
          style={{ bottom: bottomOffsetPx }}
        >
          <LidarCanvas
            onEmptySpaceClick={handleEmptySpaceClick}
            pointCloudData={pointCloudData}
            egoPose={currentFrame?.ego_pose ? {
              position: currentFrame.ego_pose.position,
              rotation: currentFrame.ego_pose.rotation,
            } : undefined}
            egoToLidarCalibration={scene?.calibration?.ego_to_lidar}
            cameraCalibrations={scene?.calibration?.lidar_to_cameras}
            getImageUrl={getImageUrl}
            getOriginalImageUrl={getOriginalImageUrl}
            isQAMode={effectiveQAMode}
            onFlagMissingLocation={handleFlagMissingLocation}
            onPointCloudClick={handlePointCloudClick}
            rightInset={showAnnotationList ? annotationPanelWidth : 0}
          />
          <CoordinateDisplay />
          {loadingLidar && (
            <div className="absolute top-4 left-1/2 transform -translate-x-1/2 bg-dark-panel/90 px-4 py-2 rounded-lg text-white text-sm">
              Loading point cloud...
            </div>
          )}
        </div>
      )}

      {/* 4D LiDAR Canvas */}
      {viewMode === '4d' && (
        <div
          className="absolute top-12 left-0 right-0 transition-all duration-300"
          style={{ bottom: 0 }}
        >
          <LidarCanvas4DNew
            onStackedDataReady={setStackedPointCloud4D}
          />
        </div>
      )}

      {/* Orthographic Views Panel */}
      {viewMode === '4d' ? (
        <OrthographicViews4D
          isVisible={showOrthoViews}
          pointCloud={stackedPointCloud4D
            ? { positions: stackedPointCloud4D.positions, intensities: new Float32Array(stackedPointCloud4D.pointCount), pointCount: stackedPointCloud4D.pointCount }
            : pointCloudData}
          worldOrigin={stackedPointCloud4D?.origin}
          rightOffset={(effectiveQAMode && effectiveStage !== 'annotation' ? 384 : isRevisionPanelVisible ? 320 : (!effectiveQAMode && showAnnotationList ? annotationPanelWidth : 0))}
          onWidthChange={setOrthoViewsWidth}
          onActiveViewChange={setActiveOrthoView}
          onCollapse={() => setShowOrthoViews(false)}
        />
      ) : (
        <OrthographicViews
          isVisible={showOrthoViews && viewMode !== '2d'}
          pointCloud={pointCloudData}
          onWidthChange={setOrthoViewsWidth}
          rightOffset={(effectiveQAMode && effectiveStage !== 'annotation' ? 384 : isRevisionPanelVisible ? 320 : (!effectiveQAMode && showAnnotationList ? annotationPanelWidth : 0))}
          onActiveViewChange={setActiveOrthoView}
          onCollapse={() => setShowOrthoViews(false)}
        />
      )}

      {/* Reopen tab for ortho views */}
      {viewMode !== '2d' && !showOrthoViews && selection.selectedAnnotationIds.length > 0 && (
        <button
          onClick={() => setShowOrthoViews(true)}
          title="Show orthographic views"
          aria-label="Show orthographic views"
          className="fixed top-1/2 -translate-y-1/2 z-30 flex flex-col items-center gap-1 px-1 py-3 rounded-l-lg bg-gray-800/90 border border-r-0 border-gray-700 text-gray-300 hover:text-white hover:bg-gray-700 shadow-lg transition-colors"
          style={{ right: (effectiveQAMode && effectiveStage !== 'annotation' ? 384 : isRevisionPanelVisible ? 320 : (!effectiveQAMode && showAnnotationList ? annotationPanelWidth : 0)) }}
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7M19 19l-7-7 7-7" />
          </svg>
          <span className="text-[10px] font-medium tracking-wide" style={{ writingMode: 'vertical-rl' }}>Views</span>
        </button>
      )}

      {/* Camera Views Panel */}
      {viewMode !== '2d' && viewMode !== '4d' && camerasToShow.length > 0 && (
        <FocusedCameraViews
          visibleCameras={camerasToShow}
          selectedCuboid={selectedCuboid}
          classColor={selectedClassColor}
          panelHeight={focusCamerasPanelHeight || defaultCameraPanelHeight}
          onHeightChange={setFocusCamerasPanelHeight}
          isFullWidth={isFullWidthCameraPanel}
          orthoViewsWidth={orthoViewsWidth}
          qaPanelOffset={(effectiveQAMode && effectiveStage !== 'annotation' ? 384 : isRevisionPanelVisible ? 320 : (!effectiveQAMode && showAnnotationList ? annotationPanelWidth : 0))}
          clickedPoint={clickedLidarPoint}
          onCameraClick={openCameraImageView}
        />
      )}

      {/* 2D View */}
      {viewMode === '2d' && taxonomyReady && (
        <CameraPanel viewMode={viewMode} taskId={taskId} />
      )}

      {/* 2D View loading state */}
      {viewMode === '2d' && !taxonomyReady && (
        <div className="absolute inset-0 top-12 bg-black z-10 flex items-center justify-center">
          <div className="text-gray-400 flex items-center gap-2">
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
            </svg>
            Setting taxonomy...
          </div>
        </div>
      )}

      {/* Fusion Labeling View */}
      {viewMode === 'fusion' && (
        <FusionLabelingView
          showOrthoViews={showOrthoViews}
          orthoViewsWidth={orthoViewsWidth}
          cameraPanelHeight={camerasToShow.length > 0 ? (focusCamerasPanelHeight || defaultCameraPanelHeight) : 0}
          qaPanelOffset={(effectiveQAMode && effectiveStage !== 'annotation' ? 384 : isRevisionPanelVisible ? 320 : (!effectiveQAMode && showAnnotationList ? annotationPanelWidth : 0))}
        />
      )}

      {/* Tool Palette */}
      {viewMode !== '2d' && (
        <ToolPalette availableCapabilities={availableCapabilities} isQAMode={effectiveQAMode} />
      )}

      {/* First-run placement hint */}
      <CuboidPlacementHint taskId={taskId} viewMode={viewMode} />

      {/* Clip Box Controls */}
      {viewMode !== '2d' && (
        <div
          className="fixed z-30 top-14 flex flex-col items-end gap-2"
          style={{ right: (showAnnotationList ? annotationPanelWidth : 48) + (showOrthoViews ? orthoViewsWidth : 0) }}
        >
          <ClipBoxControls />
          <ClassPickerPanel />
        </div>
      )}

      {/* Annotation List Panel */}
      {(!effectiveQAMode || effectiveStage === 'annotation') && viewMode !== '2d' && (
        <AnnotationListPanel
          isVisible={showAnnotationList}
          onToggle={() => setShowAnnotationList(!showAnnotationList)}
          onWidthChange={setAnnotationPanelWidth}
        />
      )}

      {/* Tabbed QA Panel */}
      {effectiveQAMode && effectiveStage !== 'annotation' && viewMode !== '2d' && (
        <div
          className="fixed top-12 right-0 z-50 w-96 shadow-2xl pointer-events-auto"
          style={{ height: 'calc(100vh - 48px)', maxHeight: 'calc(100vh - 48px)' }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <TabbedQAPanel
            onJumpToAnnotation={handleJumpToAnnotation}
            onSelectTrack={handleSelectTrack}
          />
        </div>
      )}

      {/* QA Feedback Panel */}
      {isRevisionPanelVisible && task && (
        <div
          className="fixed top-12 right-0 z-50 w-80 shadow-2xl pointer-events-auto border-l border-gray-700"
          style={{ height: 'calc(100vh - 48px)', maxHeight: 'calc(100vh - 48px)' }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <QAFeedbackPanel
            taskId={task.id}
            task={{
              ...task,
              revision_count: effectiveRevisionCount ?? task.revision_count,
              stage: effectiveStage ?? task.stage,
              status: effectiveStatus ?? task.status,
            }}
            onJumpToAnnotation={handleJumpToAnnotation}
          />
        </div>
      )}

      {/* QA Rejection Modal */}
      {showRejectionModal && rejectionAnnotationId && <RejectionModal />}

      {/* QA False Negative Modal */}
      {showFalseNegativeModal && falseNegativeLocation && (
        <FalseNegativeModal
          location={falseNegativeLocation}
          onFlag={handleFlagFalseNegative}
          onCreateAnnotation={handleCreateAnnotationDirectly}
          onClose={() => {
            setShowFalseNegativeModal(false);
            setFalseNegativeLocation(null);
          }}
        />
      )}

      {/* QA Complete Modal */}
      {showQACompleteModal && task && (
        <QACompleteModal
          stage={task.stage}
          onAccept={handleAcceptQA}
          onReject={handleRejectQA}
          onClose={() => setShowQACompleteModal(false)}
        />
      )}

      {/* Submission Success Modal */}
      <TaskSubmissionModal
        isOpen={showSubmissionModal}
        isLoadingNextTask={isLoadingNextTask}
        nextTask={nextTask}
        onGoToTaskList={handleGoToTaskList}
        onOpenNextTask={handleOpenNextTask}
      />

      {/* Keyboard Shortcuts Help Modal */}
      <ShortcutsHelpModal
        isOpen={showShortcutsHelp}
        onClose={() => setShowShortcutsHelp(false)}
        viewMode={viewMode}
        effectiveQAMode={effectiveQAMode}
      />

      {/* QA Annotation Comments */}
      <AnnotationComments />

      {/* Track Timeline Bar */}
      <TrackTimelineBar />

      {/* Timeline */}
      <Timeline
        isLoadingFrame={fetchingLidar}
        displayedFrameIndex={displayedFrameIndex}
      />
    </div>
  );
};

export default FusionEditorV2;
