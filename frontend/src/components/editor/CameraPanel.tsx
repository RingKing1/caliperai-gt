import React, { useState, useEffect, useCallback } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { useImageCacheStore } from '@/store/imageCacheStore';
import { useAuthStore } from '@/store/authStore';
import { ImageCanvas } from '@/components/canvas/ImageCanvas';
import { Image2DAnnotationView } from '@/components/canvas/Image2DAnnotationView';
import { CameraThumbnail } from '@/components/CameraThumbnail';

export type ViewMode = '3d' | 'fusion' | '2d' | '4d' | 'focus';

export interface CameraPanelProps {
  viewMode: ViewMode;
  taskId?: string;
}

export const CameraPanel: React.FC<CameraPanelProps> = ({ viewMode, taskId }) => {
  const { scene, selectedCameraId, setSelectedCamera, currentFrame, frames, taxonomy } = useEditorStore();
  const getCachedImage = useImageCacheStore((s) => s.getCached);
  const [isExpanded, setIsExpanded] = useState(true); // Expanded by default
  const [height, setHeight] = useState(280); // Larger default height
  const [isResizing, setIsResizing] = useState(false);

  const cameras = scene?.storage_paths?.cameras
    ? Object.keys(scene.storage_paths.cameras)
    : ['front_camera', 'front_left_camera', 'front_right_camera', 'rear_camera'];

  // Handle resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const newHeight = window.innerHeight - e.clientY;
      setHeight(Math.max(100, Math.min(newHeight, 600)));
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  // Build image URL for the selected camera (check cache first, then fallback to API)
  // For thumbnails (isThumb=true), requests a resized version from API for faster initial load
  const getImageUrl = useCallback(
    (cameraId: string, isThumb: boolean = false): string | undefined => {
      if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
      const filename = currentFrame.file_paths.cameras[cameraId];
      const fullPath = `${basePath}/${filename}`;

      // Check cache first for instant load
      const cached = getCachedImage(fullPath);
      if (cached) {
        return cached; // Return blob URL (always full resolution)
      }

      // Fallback to API endpoint - use smaller size for thumbnails
      const token = useAuthStore.getState().accessToken;
      const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
      const params = new URLSearchParams();
      if (token) params.append('token', token);
      if (isThumb) params.append('width', '400'); // Thumbnail width for faster load
      return `${baseUrl}?${params.toString()}`;
    },
    [scene?.storage_paths?.cameras, currentFrame?.file_paths?.cameras, getCachedImage]
  );

  // Build original API image URL (never returns cached blob URL)
  // Used for SAM2 embedding since backend can't fetch blob URLs
  const getOriginalImageUrl = useCallback(
    (cameraId: string): string | undefined => {
      if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
      const filename = currentFrame.file_paths.cameras[cameraId];

      // Always return API endpoint (never cached blob)
      const token = useAuthStore.getState().accessToken;
      const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
      return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
    },
    [scene?.storage_paths?.cameras, currentFrame?.file_paths?.cameras]
  );

  // Build image URL for any frame by frame ID (check cache first for preloading)
  const getFrameImageUrl = useCallback(
    (frameId: string, cameraId: string): string | undefined => {
      if (!scene?.storage_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      // Find the frame by ID
      const frame = frames.find((f) => f.id === frameId);
      if (!frame?.file_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
      const filename = frame.file_paths.cameras[cameraId];
      const fullPath = `${basePath}/${filename}`;

      // Check cache first for instant load
      const cached = getCachedImage(fullPath);
      if (cached) {
        return cached; // Return blob URL
      }

      // Fallback to API endpoint
      const token = useAuthStore.getState().accessToken;
      const baseUrl = `/api/v1/data/image/${fullPath}`;
      return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
    },
    [scene?.storage_paths?.cameras, frames, getCachedImage]
  );

  // Build original API image URL for any frame (never returns cached blob URL)
  // Used for SAM2/video propagation since backend can't fetch blob URLs
  const getOriginalFrameImageUrl = useCallback(
    (frameId: string, cameraId: string): string | undefined => {
      if (!scene?.storage_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      const frame = frames.find((f) => f.id === frameId);
      if (!frame?.file_paths?.cameras?.[cameraId]) {
        return undefined;
      }
      const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
      const filename = frame.file_paths.cameras[cameraId];
      const fullPath = `${basePath}/${filename}`;

      // Always return API endpoint (never cached blob)
      const token = useAuthStore.getState().accessToken;
      const baseUrl = `/api/v1/data/image/${fullPath}`;
      return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
    },
    [scene?.storage_paths?.cameras, frames]
  );

  // In fusion view, show camera selector differently
  if (viewMode === 'fusion') {
    return (
      <div className="absolute right-0 top-12 bottom-0 w-1/2 border-l border-gray-700 overflow-hidden">
        {/* Camera tabs */}
        <div className="absolute top-0 left-0 right-0 h-10 bg-dark-panel border-b border-gray-700 flex items-center px-2 gap-1 overflow-x-auto z-10">
          {cameras.map((camera) => (
            <button
              key={camera}
              onClick={() => setSelectedCamera(camera)}
              className={`px-3 py-1.5 rounded text-xs whitespace-nowrap transition-colors ${
                selectedCameraId === camera
                  ? 'bg-primary text-white'
                  : 'text-gray-400 hover:bg-dark-hover hover:text-white'
              }`}
            >
              {camera.replace(/_/g, ' ')}
            </button>
          ))}
        </div>

        {/* Image canvas */}
        <div className="absolute top-10 bottom-0 left-0 right-0">
          <ImageCanvas cameraId={selectedCameraId} imageUrl={getImageUrl(selectedCameraId)} />
        </div>
      </div>
    );
  }

  // In 2D view, show full screen camera view with CVAT-like annotation tools
  if (viewMode === '2d') {
    const frameId = currentFrame?.id || `frame-${currentFrame?.frame_index ?? 0}`;
    const frameIndex = currentFrame?.frame_index ?? 0;

    // Convert frames to the format expected by Image2DAnnotationView
    const frameInfos = frames.map((f) => ({
      id: f.id,
      frame_index: f.frame_index,
    }));

    return (
      <div className="absolute inset-0 top-12 bg-black z-10">
        <Image2DAnnotationView
          cameras={cameras}
          getImageUrl={getImageUrl}
          getOriginalImageUrl={getOriginalImageUrl}
          getFrameImageUrl={getFrameImageUrl}
          getOriginalFrameImageUrl={getOriginalFrameImageUrl}
          frameId={frameId}
          frameIndex={frameIndex}
          frames={frameInfos}
          taskId={taskId}
          taxonomy={
            taxonomy
              ? {
                  classes: taxonomy.classes.map((c) => ({
                    id: c.id,
                    name: c.name,
                    color: c.color,
                    attributes: c.attributes,
                  })),
                  shared_attributes: taxonomy.shared_attributes,
                }
              : undefined
          }
        />
      </div>
    );
  }

  // In 3D view, show collapsible camera thumbnails
  return (
    <>
      {/* Toggle button - Floating Capsule Style */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={`fixed left-4 z-30 px-4 py-2.5 bg-gray-900/40 backdrop-blur-xl border border-white/10 rounded-full shadow-2xl text-white/80 hover:text-white hover:bg-gray-900/60 hover:border-white/20 transition-all duration-300 flex items-center gap-2`}
        style={{ bottom: isExpanded ? height + 16 : 32 }}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
          />
        </svg>
        <span className="text-xs font-medium">Cameras</span>
        <svg
          className={`w-3 h-3 transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
        </svg>
      </button>

      <div
        className={`absolute left-0 right-0 bottom-0 z-20 transition-all duration-300`}
        style={{ height: isExpanded ? height : 0 }}
      >
        {isExpanded && (
          <div className="h-full bg-dark-panel/95 backdrop-blur-sm border-t border-gray-700 relative">
            {/* Resize Handle */}
            <div
              className="absolute top-0 left-0 right-0 h-1 cursor-ns-resize hover:bg-primary/50 z-50"
              onMouseDown={(e) => {
                e.preventDefault();
                setIsResizing(true);
              }}
            />

            <div className="flex items-center gap-3 h-full px-4 overflow-x-auto pt-2 pb-2">
              {cameras.map((camera) => (
                <CameraThumbnail
                  key={`${camera}-${currentFrame?.id}`}
                  camera={camera}
                  imageUrl={getImageUrl(camera, true)}
                  isSelected={selectedCameraId === camera}
                  onClick={() => {
                    // Activate camera view mode - moves 3D camera to match and shows image plane
                    useEditorStore.getState().activateCameraView(camera);
                  }}
                  onDoubleClick={() => {
                    // Double-click to deactivate camera view and return to normal 3D view
                    useEditorStore.getState().deactivateCameraView();
                  }}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
};
