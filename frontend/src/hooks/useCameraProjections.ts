import { useState, useMemo, useCallback, useEffect } from 'react';
import { useEditorStore, useSelectedAnnotations } from '@/store/editorStore';
import { useAuthStore } from '@/store/authStore';
import { useImageCacheStore } from '@/store/imageCacheStore';
import { findVisibleCamerasForCuboid, findBestCameraForPoint } from '@/utils/projection';
import type { CuboidData } from '@/types';

export const useCameraProjections = () => {
  const scene = useEditorStore((s) => s.scene);
  const currentFrame = useEditorStore((s) => s.currentFrame);
  const currentFrameIndex = useEditorStore((s) => s.currentFrameIndex);
  const frames = useEditorStore((s) => s.frames);
  const selection = useEditorStore((s) => s.selection);
  const taxonomy = useEditorStore((s) => s.taxonomy);

  const [visibleCamerasForSelection, setVisibleCamerasForSelection] = useState<string[]>([]);
  const [clickedLidarPoint, setClickedLidarPoint] = useState<{ x: number; y: number; z: number } | null>(null);
  const [focusCamerasPanelHeight, setFocusCamerasPanelHeight] = useState(window.innerHeight * 0.35);

  const selectedAnnotations = useSelectedAnnotations();

  // Get selected cuboid data for projection
  const selectedCuboid = useMemo<CuboidData | null>(() => {
    if (selectedAnnotations.length === 0) return null;
    const ann = selectedAnnotations[0];
    if (ann.type !== 'cuboid') return null;
    const data = ann.data as CuboidData;
    if (!data?.center || !data?.dimensions) return null;
    return data;
  }, [selectedAnnotations]);

  // Get class color for selected annotation
  const selectedClassColor = useMemo(() => {
    if (selectedAnnotations.length === 0) return '#00ff00';
    const ann = selectedAnnotations[0];
    const classDef = taxonomy?.classes.find((c) => c.id === ann.class_id);
    return classDef?.color || '#00ff00';
  }, [selectedAnnotations, taxonomy]);

  // All cameras from scene
  const allCameras = useMemo(() => {
    if (!scene?.storage_paths?.cameras) {
      return ['front_camera', 'front_left_camera', 'front_right_camera', 'rear_camera'];
    }
    return Object.keys(scene.storage_paths.cameras);
  }, [scene?.storage_paths?.cameras]);

  const hasSelection = selection.selectedAnnotationIds.length > 0 && selectedCuboid !== null;
  const hasPointCameras = !hasSelection && visibleCamerasForSelection.length > 0;
  const camerasToShow = (hasSelection || hasPointCameras) ? visibleCamerasForSelection : allCameras;
  const isFullWidthCameraPanel = !hasSelection && !hasPointCameras;
  const defaultCameraPanelHeight = isFullWidthCameraPanel ? 280 : 200;

  const getCachedImage = useImageCacheStore((s) => s.getCached);

  const getImageUrl = useCallback((cameraId: string): string | undefined => {
    if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
      return undefined;
    }
    const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
    const filename = currentFrame.file_paths.cameras[cameraId];
    const fullPath = `${basePath}/${filename}`;

    const cached = getCachedImage(fullPath);
    if (cached) {
      return cached;
    }

    const token = useAuthStore.getState().accessToken;
    const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
    return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
  }, [scene?.storage_paths?.cameras, currentFrame?.file_paths?.cameras, getCachedImage]);

  const getOriginalImageUrl = useCallback((cameraId: string): string | undefined => {
    if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
      return undefined;
    }
    const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
    const filename = currentFrame.file_paths.cameras[cameraId];

    const token = useAuthStore.getState().accessToken;
    const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
    return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
  }, [scene?.storage_paths?.cameras, currentFrame?.file_paths?.cameras]);

  // Preload images for nearby frames
  useEffect(() => {
    if (!scene?.storage_paths?.cameras || !currentFrame) return;

    const preloadRange = 2;
    const cameras = Object.keys(scene.storage_paths.cameras);

    const framesToPreload = frames.slice(
      Math.max(0, currentFrameIndex - preloadRange),
      Math.min(frames.length, currentFrameIndex + preloadRange + 1)
    );

    framesToPreload.forEach((frame) => {
      cameras.forEach((cameraId) => {
        const filename = frame.file_paths?.cameras?.[cameraId];
        if (!filename) return;

        const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
        const fullPath = `${basePath}/${filename}`;
        const cached = getCachedImage(fullPath);

        if (cached) {
          const img = new Image();
          img.src = cached;
        }
      });
    });
  }, [scene, currentFrame, currentFrameIndex, frames, getCachedImage]);

  // Compute visible cameras for selected cuboid
  useEffect(() => {
    if (!selectedCuboid || !scene?.calibration?.lidar_to_cameras) {
      setVisibleCamerasForSelection([]);
      return;
    }
    setClickedLidarPoint(null);

    try {
      const lidarToCameras = scene.calibration.lidar_to_cameras;
      const defaultImageSize = { width: 1920, height: 1080 };
      const visibleCameras = findVisibleCamerasForCuboid(
        selectedCuboid,
        lidarToCameras,
        defaultImageSize,
        2
      );
      setVisibleCamerasForSelection(visibleCameras);
    } catch (error) {
      console.warn('[useCameraProjections] Error computing visible cameras:', error);
      setVisibleCamerasForSelection([]);
    }
  }, [selectedCuboid, scene?.calibration?.lidar_to_cameras]);

  const handleEmptySpaceClick = useCallback(() => {
    useEditorStore.getState().deselectAll();
    setVisibleCamerasForSelection([]);
    setClickedLidarPoint(null);
  }, []);

  const handlePointCloudClick = useCallback((point: { x: number; y: number; z: number }) => {
    // Clicking on point cloud: deselect any active annotation but preserve active track session
    useEditorStore.getState().deselectAll();
    setVisibleCamerasForSelection([]);
    setClickedLidarPoint(null);

    if (!scene?.calibration?.lidar_to_cameras) return;

    try {
      const defaultImageSize = { width: 1920, height: 1080 };
      const bestCamera = findBestCameraForPoint(
        point,
        scene.calibration.lidar_to_cameras,
        defaultImageSize
      );
      if (bestCamera) {
        setVisibleCamerasForSelection([bestCamera]);
        setClickedLidarPoint(point);
      } else {
        setClickedLidarPoint(null);
      }
    } catch (error) {
      console.warn('[useCameraProjections] Error computing visible cameras for point:', error);
    }
  }, [scene?.calibration?.lidar_to_cameras]);

  const openCameraImageView = useCallback((cameraId: string) => {
    useEditorStore.getState().activateCameraView(cameraId);
    useEditorStore.getState().setLidarView({
      cameraView: {
        ...useEditorStore.getState().lidarView.cameraView,
        imageOnlyMode: true,
      },
    });
  }, []);

  return {
    visibleCamerasForSelection,
    setVisibleCamerasForSelection,
    clickedLidarPoint,
    setClickedLidarPoint,
    focusCamerasPanelHeight,
    setFocusCamerasPanelHeight,
    selectedCuboid,
    selectedClassColor,
    allCameras,
    camerasToShow,
    isFullWidthCameraPanel,
    defaultCameraPanelHeight,
    getImageUrl,
    getOriginalImageUrl,
    handleEmptySpaceClick,
    handlePointCloudClick,
    openCameraImageView,
  };
};
