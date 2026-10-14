import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useEditorStore, useCurrentFrameAnnotations } from '@/store/editorStore';
import { useImageCacheStore } from '@/store/imageCacheStore';
import { useAuthStore } from '@/store/authStore';
import { projectCuboidToAllCameras } from '@/utils/projection';
import type { CuboidData, BBox2D } from '@/types';
import type { FusionLabel } from './types';

export const useFusionLabels = () => {
  const { scene } = useEditorStore();
  const currentFrameAnnotations = useCurrentFrameAnnotations();

  const cuboidAnnotations = useMemo(() =>
    currentFrameAnnotations.filter(ann => ann.type === 'cuboid'),
    [currentFrameAnnotations]
  );

  const lidarToCameras = useMemo(() => {
    if (!scene?.calibration?.lidar_to_cameras) return {};
    return scene.calibration.lidar_to_cameras;
  }, [scene?.calibration]);

  const cameras = useMemo(() =>
    scene?.storage_paths?.cameras ? Object.keys(scene.storage_paths.cameras) : [],
    [scene?.storage_paths?.cameras]
  );

  const imageSize = useMemo(() => ({ width: 1600, height: 900 }), []);

  const fusionLabels = useMemo(() => {
    if (!cuboidAnnotations.length || !Object.keys(lidarToCameras).length) {
      return new Map<string, FusionLabel[]>();
    }

    const labels = new Map<string, FusionLabel[]>();

    for (const ann of cuboidAnnotations) {
      const cuboidData = ann.data as CuboidData;
      const projections = projectCuboidToAllCameras(cuboidData, lidarToCameras, imageSize);

      for (const [cameraId, bbox] of Object.entries(projections)) {
        const fusionLabel: FusionLabel = {
          annotationId: ann.id,
          cameraId,
          bbox,
          classId: ann.class_id,
          trackId: ann.track_id,
          isManuallyAdjusted: false,
        };

        if (!labels.has(ann.id)) {
          labels.set(ann.id, []);
        }
        labels.get(ann.id)!.push(fusionLabel);
      }
    }

    return labels;
  }, [cuboidAnnotations, lidarToCameras, imageSize]);

  const camerasWithLabels = useMemo(() => {
    const cameraSet = new Set<string>();
    fusionLabels.forEach((annLabels) => {
      annLabels.forEach(l => cameraSet.add(l.cameraId));
    });
    return Array.from(cameraSet);
  }, [fusionLabels]);

  const labelsByCamera = useMemo(() => {
    const grouped: Record<string, FusionLabel[]> = {};
    fusionLabels.forEach((annLabels) => {
      annLabels.forEach(label => {
        if (!grouped[label.cameraId]) {
          grouped[label.cameraId] = [];
        }
        grouped[label.cameraId].push(label);
      });
    });
    return grouped;
  }, [fusionLabels]);

  return {
    fusionLabels,
    camerasWithLabels,
    labelsByCamera,
    cameras,
    lidarToCameras,
    cuboidAnnotations,
  };
};

export interface FusionLabelingViewProps {
  showOrthoViews?: boolean;
  orthoViewsWidth?: number;
  cameraPanelHeight?: number;
  qaPanelOffset?: number;
}

export const FusionLabelingView: React.FC<FusionLabelingViewProps> = ({
  showOrthoViews = false,
  orthoViewsWidth = 480,
  cameraPanelHeight = 0,
  qaPanelOffset = 0,
}) => {
  const {
    scene,
    currentFrame,
    taxonomy,
    selection,
    selectAnnotation,
  } = useEditorStore();
  const getCachedImage = useImageCacheStore((s) => s.getCached);

  // Use the shared fusion labels hook
  const { cameras, lidarToCameras, cuboidAnnotations, camerasWithLabels } = useFusionLabels();

  // State for manual adjustments (Map<labelKey, BBox2D>)
  const [manualAdjustments, setManualAdjustments] = useState<Map<string, BBox2D>>(new Map());

  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [_editingLabel, setEditingLabel] = useState<string | null>(null);
  const [dragState, setDragState] = useState<{
    labelKey: string;
    startX: number;
    startY: number;
    startBbox: BBox2D;
    mode: 'move' | 'resize-br' | 'resize-tl' | 'resize-tr' | 'resize-bl';
  } | null>(null);

  // Container and image refs for proper overlay positioning
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [imageNaturalSize, setImageNaturalSize] = useState<{ width: number; height: number }>({ width: 1600, height: 900 });
  const [imageDisplayBounds, setImageDisplayBounds] = useState<{ x: number; y: number; width: number; height: number } | null>(null);

  // Use a stable reference for image size to avoid triggering re-renders
  const imageSizeRef = useRef({ width: 1600, height: 900 });

  // Use the natural size for rendering (this is what the SVG viewBox should use)
  const imageSize = imageNaturalSize;

  // Track if first camera has been auto-selected
  const hasAutoSelectedRef = useRef(false);

  // Update the ref when natural size changes (no state update, just ref)
  useEffect(() => {
    imageSizeRef.current = imageNaturalSize;
  }, [imageNaturalSize]);

  // Compute fusion labels from 3D annotations using useMemo
  const computedFusionLabels = useMemo(() => {
    if (!cuboidAnnotations.length || !Object.keys(lidarToCameras).length) {
      return new Map<string, FusionLabel[]>();
    }

    const newLabels = new Map<string, FusionLabel[]>();
    const currentImageSize = imageSizeRef.current;

    for (const ann of cuboidAnnotations) {
      const cuboidData = ann.data as CuboidData;
      const projections = projectCuboidToAllCameras(cuboidData, lidarToCameras, currentImageSize);

      for (const [cameraId, bbox] of Object.entries(projections)) {
        const labelKey = `${ann.id}-${cameraId}`;

        // Check if we have a manual adjustment
        const manualBbox = manualAdjustments.get(labelKey);

        const fusionLabel: FusionLabel = {
          annotationId: ann.id,
          cameraId,
          bbox: manualBbox || bbox,
          classId: ann.class_id,
          trackId: ann.track_id,
          isManuallyAdjusted: !!manualBbox,
        };

        if (!newLabels.has(ann.id)) {
          newLabels.set(ann.id, []);
        }
        newLabels.get(ann.id)!.push(fusionLabel);
      }
    }

    return newLabels;
  }, [cuboidAnnotations, lidarToCameras, manualAdjustments]);

  // Auto-select first camera with visible labels (only once)
  useEffect(() => {
    if (!selectedCameraId && !hasAutoSelectedRef.current && computedFusionLabels.size > 0) {
      const firstLabels = Array.from(computedFusionLabels.values())[0];
      if (firstLabels && firstLabels.length > 0) {
        setSelectedCameraId(firstLabels[0].cameraId);
        hasAutoSelectedRef.current = true;
      }
    }
  }, [computedFusionLabels, selectedCameraId]);

  // Get labels for selected camera
  const labelsForCamera = useMemo(() => {
    if (!selectedCameraId) return [];
    const labels: FusionLabel[] = [];
    computedFusionLabels.forEach((annLabels) => {
      const label = annLabels.find(l => l.cameraId === selectedCameraId);
      if (label) labels.push(label);
    });
    return labels;
  }, [computedFusionLabels, selectedCameraId]);

  // Build image URL - check cache first for instant display
  const getImageUrl = (cameraId: string): string | undefined => {
    if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
      return undefined;
    }
    const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
    const filename = currentFrame.file_paths.cameras[cameraId];
    const fullPath = `${basePath}/${filename}`;

    // Check cache first for instant load
    const cached = getCachedImage(fullPath);
    if (cached) {
      return cached;
    }

    // Fallback to API
    const token = useAuthStore.getState().accessToken;
    const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
    return token ? `${baseUrl}?token=${encodeURIComponent(token)}` : baseUrl;
  };

  // Compute image display bounds when container or image changes
  const updateImageDisplayBounds = useCallback(() => {
    if (!containerRef.current || !imageRef.current) return;

    const container = containerRef.current.getBoundingClientRect();
    const img = imageRef.current;

    if (!img.naturalWidth || !img.naturalHeight) return;

    // Compute how object-contain positions the image
    const containerAspect = container.width / container.height;
    const imageAspect = img.naturalWidth / img.naturalHeight;

    let displayWidth: number, displayHeight: number;
    let offsetX: number, offsetY: number;

    if (imageAspect > containerAspect) {
      // Image is wider - fits to width
      displayWidth = container.width;
      displayHeight = container.width / imageAspect;
      offsetX = 0;
      offsetY = (container.height - displayHeight) / 2;
    } else {
      // Image is taller - fits to height
      displayHeight = container.height;
      displayWidth = container.height * imageAspect;
      offsetX = (container.width - displayWidth) / 2;
      offsetY = 0;
    }

    setImageDisplayBounds({
      x: offsetX,
      y: offsetY,
      width: displayWidth,
      height: displayHeight,
    });
  }, []);

  // Handle image load
  const handleImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    setImageNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
    updateImageDisplayBounds();
  }, [updateImageDisplayBounds]);

  // Update bounds on resize (window or container)
  useEffect(() => {
    const handleResize = () => updateImageDisplayBounds();
    window.addEventListener('resize', handleResize);

    // Also observe container resize (e.g. when ortho views toggle)
    let resizeObserver: ResizeObserver | null = null;
    if (containerRef.current) {
      resizeObserver = new ResizeObserver(() => {
        updateImageDisplayBounds();
      });
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      window.removeEventListener('resize', handleResize);
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
    };
  }, [updateImageDisplayBounds]);

  // Update bounds when image changes
  useEffect(() => {
    updateImageDisplayBounds();
  }, [selectedCameraId, currentFrame, updateImageDisplayBounds]);

  // Handle label drag/resize
  const handleLabelMouseDown = (e: React.MouseEvent, label: FusionLabel, mode: 'move' | 'resize-br' | 'resize-tl' | 'resize-tr' | 'resize-bl') => {
    e.stopPropagation();
    e.preventDefault();
    const labelKey = `${label.annotationId}-${label.cameraId}`;
    setDragState({
      labelKey,
      startX: e.clientX,
      startY: e.clientY,
      startBbox: { ...label.bbox },
      mode,
    });
    setEditingLabel(labelKey);
    selectAnnotation(label.annotationId);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragState || !imageDisplayBounds) return;

    const dx = e.clientX - dragState.startX;
    const dy = e.clientY - dragState.startY;

    // Scale factor for image display based on actual rendered size
    const scaleX = imageSize.width / imageDisplayBounds.width;
    const scaleY = imageSize.height / imageDisplayBounds.height;

    const scaledDx = dx * scaleX;
    const scaledDy = dy * scaleY;

    let newBbox: BBox2D;

    if (dragState.mode === 'move') {
      newBbox = {
        x: Math.max(0, dragState.startBbox.x + scaledDx),
        y: Math.max(0, dragState.startBbox.y + scaledDy),
        width: dragState.startBbox.width,
        height: dragState.startBbox.height,
      };
    } else {
      // Resize modes
      const { x, y, width, height } = dragState.startBbox;
      switch (dragState.mode) {
        case 'resize-br':
          newBbox = {
            x, y,
            width: Math.max(20, width + scaledDx),
            height: Math.max(20, height + scaledDy),
          };
          break;
        case 'resize-tl':
          newBbox = {
            x: x + scaledDx,
            y: y + scaledDy,
            width: Math.max(20, width - scaledDx),
            height: Math.max(20, height - scaledDy),
          };
          break;
        case 'resize-tr':
          newBbox = {
            x, y: y + scaledDy,
            width: Math.max(20, width + scaledDx),
            height: Math.max(20, height - scaledDy),
          };
          break;
        case 'resize-bl':
          newBbox = {
            x: x + scaledDx, y,
            width: Math.max(20, width - scaledDx),
            height: Math.max(20, height + scaledDy),
          };
          break;
        default:
          newBbox = dragState.startBbox;
      }
    }

    // Update manual adjustments state
    setManualAdjustments(prev => {
      const next = new Map(prev);
      next.set(dragState.labelKey, newBbox);
      return next;
    });
  };

  const handleMouseUp = () => {
    setDragState(null);
  };

  // Get class color
  const getClassColor = (classId: string): string => {
    const classDef = taxonomy?.classes?.find(c => c.id === classId);
    return classDef?.color || '#00ff00';
  };

  // Calculate right offset and width based on ortho views visibility and dynamic width
  const totalRightOffset = (showOrthoViews ? orthoViewsWidth : 0) + qaPanelOffset;
  const rightOffset = `${totalRightOffset}px`;
  const panelWidth = showOrthoViews ? `calc(50% - ${orthoViewsWidth / 2}px)` : '50%';
  const bottomOffset = cameraPanelHeight > 0 ? `${cameraPanelHeight}px` : '0';

  if (cameras.length === 0) {
    return (
      <div
        className="absolute top-12 bg-dark-panel flex items-center justify-center text-gray-500 transition-all duration-300"
        style={{ width: panelWidth, right: rightOffset, bottom: bottomOffset }}
      >
        No cameras available
      </div>
    );
  }

  return (
    <div
      className="absolute top-12 border-l border-gray-700 flex flex-col bg-dark-panel transition-all duration-300"
      style={{ width: panelWidth, right: rightOffset, bottom: bottomOffset }}
    >
      {/* Camera Tabs */}
      <div className="h-10 bg-dark-panel border-b border-gray-700 flex items-center px-2 gap-1 overflow-x-auto flex-shrink-0">
        {cameras.map((camera) => {
          const hasLabels = camerasWithLabels.includes(camera);
          return (
            <button
              key={camera}
              onClick={() => setSelectedCameraId(camera)}
              className={`px-3 py-1.5 rounded text-xs whitespace-nowrap transition-colors flex items-center gap-1.5 ${
                selectedCameraId === camera
                  ? 'bg-primary text-white'
                  : hasLabels
                    ? 'text-green-400 hover:bg-dark-hover hover:text-green-300 border border-green-500/30'
                    : 'text-gray-400 hover:bg-dark-hover hover:text-white'
              }`}
            >
              {hasLabels && (
                <span className="w-2 h-2 bg-green-400 rounded-full" />
              )}
              {camera.replace(/_/g, ' ')}
            </button>
          );
        })}
      </div>

      {/* Image with Labels */}
      <div
        ref={containerRef}
        className="flex-1 relative overflow-hidden bg-black flex items-center justify-center"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {selectedCameraId && getImageUrl(selectedCameraId) && (
          <>
            <img
              ref={imageRef}
              src={getImageUrl(selectedCameraId)}
              alt={selectedCameraId}
              className="w-full h-full object-contain"
              draggable={false}
              onLoad={handleImageLoad}
            />

            {/* Overlay for labels - positioned exactly over the image */}
            {imageDisplayBounds && (
              <svg
                className="absolute pointer-events-none"
                style={{
                  left: imageDisplayBounds.x,
                  top: imageDisplayBounds.y,
                  width: imageDisplayBounds.width,
                  height: imageDisplayBounds.height,
                }}
                viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
                preserveAspectRatio="none"
              >
              {labelsForCamera.map((label) => {
                const isSelected = selection.selectedAnnotationIds.includes(label.annotationId);
                const color = getClassColor(label.classId);
                const { x, y, width, height } = label.bbox;

                return (
                  <g key={`${label.annotationId}-${label.cameraId}`} className="pointer-events-auto">
                    {/* Main bounding box */}
                    <rect
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill="transparent"
                      stroke={color}
                      strokeWidth={isSelected ? 3 : 2}
                      strokeDasharray={label.isManuallyAdjusted ? "none" : "5,5"}
                      className="cursor-move"
                      onMouseDown={(e) => handleLabelMouseDown(e as any, label, 'move')}
                    />

                    {/* Label tag */}
                    <rect
                      x={x}
                      y={y - 24}
                      width={Math.max(80, label.classId.length * 8 + (label.trackId ? 50 : 0))}
                      height={22}
                      fill={color}
                      rx={2}
                    />
                    <text
                      x={x + 4}
                      y={y - 8}
                      fill="white"
                      fontSize={12}
                      fontFamily="monospace"
                    >
                      {label.classId}{label.trackId ? ` | ${label.trackId}` : ''}
                    </text>

                    {/* Resize handles (only when selected) */}
                    {isSelected && (
                      <>
                        {/* Corner handles */}
                        <rect x={x - 4} y={y - 4} width={8} height={8} fill={color}
                          className="cursor-nwse-resize"
                          onMouseDown={(e) => handleLabelMouseDown(e as any, label, 'resize-tl')}
                        />
                        <rect x={x + width - 4} y={y - 4} width={8} height={8} fill={color}
                          className="cursor-nesw-resize"
                          onMouseDown={(e) => handleLabelMouseDown(e as any, label, 'resize-tr')}
                        />
                        <rect x={x - 4} y={y + height - 4} width={8} height={8} fill={color}
                          className="cursor-nesw-resize"
                          onMouseDown={(e) => handleLabelMouseDown(e as any, label, 'resize-bl')}
                        />
                        <rect x={x + width - 4} y={y + height - 4} width={8} height={8} fill={color}
                          className="cursor-nwse-resize"
                          onMouseDown={(e) => handleLabelMouseDown(e as any, label, 'resize-br')}
                        />
                      </>
                    )}

                    {/* Manual adjustment indicator */}
                    {label.isManuallyAdjusted && (
                      <circle
                        cx={x + width - 8}
                        cy={y + 8}
                        r={6}
                        fill="#f59e0b"
                        stroke="white"
                        strokeWidth={1}
                      />
                    )}
                  </g>
                );
              })}
              </svg>
            )}
          </>
        )}

        {/* No image placeholder */}
        {selectedCameraId && !getImageUrl(selectedCameraId) && (
          <div className="flex items-center justify-center h-full text-gray-500">
            No image available for {selectedCameraId}
          </div>
        )}

        {!selectedCameraId && (
          <div className="flex items-center justify-center h-full text-gray-500">
            Select a camera to view fusion labels
          </div>
        )}
      </div>

      {/* Info bar */}
      <div className="h-8 bg-dark-panel border-t border-gray-700 flex items-center justify-between px-3 text-xs text-gray-400 flex-shrink-0">
        <span>
          {labelsForCamera.length} label{labelsForCamera.length !== 1 ? 's' : ''} in view
        </span>
        <span>
          {camerasWithLabels.length} camera{camerasWithLabels.length !== 1 ? 's' : ''} with labels
        </span>
      </div>
    </div>
  );
};
