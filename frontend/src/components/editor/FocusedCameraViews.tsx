import React, { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useEditorStore, useCurrentFrameAnnotations } from '@/store/editorStore';
import { useImageCacheStore } from '@/store/imageCacheStore';
import { useAuthStore } from '@/store/authStore';
import type { CuboidData } from '@/types';

export interface FocusedCameraViewsProps {
  visibleCameras: string[];
  selectedCuboid: CuboidData | null;
  classColor: string;
  panelHeight: number;
  onHeightChange: (height: number) => void;
  isFullWidth?: boolean; // True when showing all cameras (no selection)
  orthoViewsWidth?: number; // Width of orthographic views panel for dynamic sizing
  qaPanelOffset?: number; // Additional offset for QA panel when in QA mode
  clickedPoint?: { x: number; y: number; z: number } | null;
  onCameraClick?: (cameraId: string) => void; // Override camera card click behavior
}

// Single camera view with projected cuboid overlay
export const FocusedCameraCard: React.FC<{
  cameraId: string;
  imageUrl: string | undefined;
  selectedCuboid: CuboidData | null;
  classColor: string;
  onClick: () => void;
  clickedPoint?: { x: number; y: number; z: number } | null;
  allCuboids?: Array<{ cuboid: CuboidData; color: string; accepted: boolean }>;
}> = React.memo(({ cameraId, imageUrl, selectedCuboid, classColor, onClick, clickedPoint, allCuboids }) => {
  const scene = useEditorStore(state => state.scene);
  const useFisheyeProjection = useEditorStore(state => state.lidarView.useFisheyeProjection);
  const clipBox = useEditorStore(state => state.lidarView.clipBox);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });
  // Bumped when full-res image loads so canvas draws with correct naturalWidth/Height
  const [_imgVersion, setImgVersion] = useState(0);

  // Zoom and pan state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const lastPointer = useRef({ x: 0, y: 0 });

  // Get camera calibration
  const cameraCalib = scene?.calibration?.lidar_to_cameras?.[cameraId];

  // Store stable image dimensions - use calibration data as primary source
  // This avoids projection jitter when switching frames (naturalWidth might be 0 briefly)
  const stableImageSize = useMemo(() => {
    if (!cameraCalib?.intrinsic) return { width: 1920, height: 1080 };
    const { cx, cy, resolution } = cameraCalib.intrinsic;
    // Prefer explicit resolution from calibration, fall back to cx*2/cy*2
    return {
      width: resolution?.[0] ?? Math.round(cx * 2),
      height: resolution?.[1] ?? Math.round(cy * 2),
    };
  }, [cameraCalib?.intrinsic]);

  // Handle cached images (already complete before React attaches onLoad)
  useEffect(() => {
    const img = imgRef.current;
    if (img && img.complete && img.naturalWidth > 0) {
      setImgVersion(v => v + 1);
    }
  }, [imageUrl]);

  // Track container size
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Draw cuboid projection on canvas — mirrors ProjectedPointsOverlay exactly.
  // Runs whenever cuboid, calibration, container size, or colour changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Use parent clientWidth/Height like ProjectedPointsOverlay does, falling back to containerSize
    const parent = canvas.parentElement;
    const w = parent?.clientWidth  || containerSize.width  || canvas.offsetWidth;
    const h = parent?.clientHeight || containerSize.height || canvas.offsetHeight;

    canvas.width  = w;
    canvas.height = h;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!cameraCalib || !canvas.width || !canvas.height) return;
    if (!selectedCuboid && !clickedPoint && !(allCuboids && allCuboids.length > 0)) return;

    // XYZ Range Filter: Skip rendering if cuboid center is outside the clipBox bounds
    if (clipBox?.enabled && selectedCuboid) {
      const center = selectedCuboid.center;
      if (center.x < clipBox.xMin || center.x > clipBox.xMax ||
          center.y < clipBox.yMin || center.y > clipBox.yMax ||
          center.z < clipBox.zMin || center.z > clipBox.zMax) {
        return;
      }
    }

    const { extrinsic, intrinsic } = cameraCalib;
    const { fx, fy, cx, cy, camera_model, distortion } = intrinsic;
    const R_stored = extrinsic.rotation;
    const t_stored = extrinsic.translation;

    // Use actual image dimensions when available, fall back to calibration-derived size
    // This matches how ProjectedPointsOverlay uses naturalWidth/naturalHeight
    const img = imgRef.current;
    const imageWidth = (img && img.naturalWidth > 0) ? img.naturalWidth : stableImageSize.width;
    const imageHeight = (img && img.naturalHeight > 0) ? img.naturalHeight : stableImageSize.height;

    // Check if extrinsics need to be inverted
    // DISABLED: Inversion was causing projections to appear in wrong cameras
    const needsInversion = false; // Disabled - see if projection appears in correct camera

    let R: number[][];
    let t: number[];

    if (needsInversion) {
      // Invert the transform: R_inv = R^T, t_inv = -R^T @ t
      R = [
        [R_stored[0][0], R_stored[1][0], R_stored[2][0]],
        [R_stored[0][1], R_stored[1][1], R_stored[2][1]],
        [R_stored[0][2], R_stored[1][2], R_stored[2][2]],
      ];
      t = [
        -(R[0][0]*t_stored[0] + R[0][1]*t_stored[1] + R[0][2]*t_stored[2]),
        -(R[1][0]*t_stored[0] + R[1][1]*t_stored[1] + R[1][2]*t_stored[2]),
        -(R[2][0]*t_stored[0] + R[2][1]*t_stored[1] + R[2][2]*t_stored[2]),
      ];
    } else {
      R = R_stored;
      t = t_stored;
    }

    // Compute displayed image area (CSS object-contain equivalent)
    const cW = canvas.width;
    const cH = canvas.height;
    const containerAspect = cW / cH;
    const imageAspect     = imageWidth / imageHeight;
    let displayWidth: number, displayHeight: number;
    if (containerAspect > imageAspect) {
      displayHeight = cH;
      displayWidth  = cH * imageAspect;
    } else {
      displayWidth  = cW;
      displayHeight = cW / imageAspect;
    }
    const oX     = (cW - displayWidth)  / 2;
    const oY     = (cH - displayHeight) / 2;
    const scaleX = displayWidth  / imageWidth;
    const scaleY = displayHeight / imageHeight;

    // Fisheye detection: small focal length relative to image + 4 distortion params
    // OR toggle is enabled OR camera_model is explicitly kannala_brandt
    const isAutoFisheye = distortion?.length === 4 && fx < imageWidth / 2;
    const useFisheye = useFisheyeProjection || camera_model === 'kannala_brandt' || isAutoFisheye;

    // Fisheye projection (Kannala-Brandt KB4 model)
    const projectFisheye = (camX: number, camY: number, camZ: number): { u: number; v: number } | null => {
      // After extrinsic inversion, no need to flip X
      const r = Math.sqrt(camX * camX + camY * camY);
      const theta = Math.atan2(r, camZ);

      if (theta > Math.PI * 0.9) return null;

      const k2 = distortion?.[0] ?? 0;
      const k3 = distortion?.[1] ?? 0;
      const k4 = distortion?.[2] ?? 0;
      const k5 = distortion?.[3] ?? 0;

      const theta2 = theta * theta;
      const theta4 = theta2 * theta2;
      const theta6 = theta4 * theta2;
      const theta8 = theta4 * theta4;
      const theta_d = theta * (1 + k2 * theta2 + k3 * theta4 + k4 * theta6 + k5 * theta8);

      if (r < 1e-8) {
        return { u: cx, v: cy };
      }
      const scale = theta_d / r;
      return {
        u: fx * scale * camX + cx,
        v: fy * scale * camY + cy
      };
    };

    // Project LiDAR point → canvas coords (with image bounds check)
    const project = (px: number, py: number, pz: number) => {
      const camX = R[0][0]*px + R[0][1]*py + R[0][2]*pz + t[0];
      const camY = R[1][0]*px + R[1][1]*py + R[1][2]*pz + t[1];
      const camZ = R[2][0]*px + R[2][1]*py + R[2][2]*pz + t[2];
      // For fisheye, allow wider angles (camZ can be down to -1.0 for ~100° off-axis)
      // For pinhole, require camZ > 0.1 (must be clearly in front)
      const minCamZ = useFisheye ? -1.0 : 0.1;
      if (camZ <= minCamZ) return null;

      let u: number, v: number;
      if (useFisheye) {
        const result = projectFisheye(camX, camY, camZ);
        if (!result) return null;
        u = result.u;
        v = result.v;
      } else {
        u = (fx * camX / camZ) + cx;
        v = (fy * camY / camZ) + cy;
      }

      // Bounds check: return null if projected point is outside image with margin
      const margin = 0.3; // 30% margin for fisheye where edges may be distorted
      const marginX = imageWidth * margin;
      const marginY = imageHeight * margin;
      if (u < -marginX || u > imageWidth + marginX || v < -marginY || v > imageHeight + marginY) {
        return null;
      }

      return {
        x: u * scaleX + oX,
        y: v * scaleY + oY,
      };
    };

    // All current-frame cuboids as thin projections (static review mode).
    // The selected cuboid is skipped here because it is drawn prominently below.
    if (allCuboids && allCuboids.length > 0) {
      const thinEdges: [number, number][] = [
        [0,1],[1,2],[2,3],[3,0],
        [4,5],[5,6],[6,7],[7,4],
        [0,4],[1,5],[2,6],[3,7],
      ];
      ctx.lineCap = 'round';
      ctx.lineWidth = 1;
      for (const item of allCuboids) {
        if (selectedCuboid && item.cuboid === selectedCuboid) continue;
        if (clipBox?.enabled) {
          const c = item.cuboid.center;
          if (c.x < clipBox.xMin || c.x > clipBox.xMax ||
              c.y < clipBox.yMin || c.y > clipBox.yMax ||
              c.z < clipBox.zMin || c.z > clipBox.zMax) continue;
        }
        const { center, dimensions, rotation } = item.cuboid;
        const yaw = rotation?.yaw ?? 0;
        const hl = ((dimensions?.length ?? 1)) / 2;
        const hw = ((dimensions?.width ?? 1)) / 2;
        const hh = ((dimensions?.height ?? 1)) / 2;
        const cosA = Math.cos(yaw);
        const sinA = Math.sin(yaw);
        const corners: [number, number, number][] = [
          [ hl,  hw, -hh], [ hl, -hw, -hh], [-hl, -hw, -hh], [-hl,  hw, -hh],
          [ hl,  hw,  hh], [ hl, -hw,  hh], [-hl, -hw,  hh], [-hl,  hw,  hh],
        ];
        const pts = corners.map(([lx, ly, lz]) =>
          project(
            center.x + cosA*lx - sinA*ly,
            center.y + sinA*lx + cosA*ly,
            center.z + lz,
          )
        );
        if (pts.filter(Boolean).length < 2) continue;
        ctx.strokeStyle = item.accepted ? '#ef4444' : item.color;
        ctx.globalAlpha = 0.75;
        for (const [i, j] of thinEdges) {
          const a = pts[i];
          const b = pts[j];
          if (!a || !b) continue;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1.0;
    }

    // Build 8 corners from cuboid data (skip if no cuboid selected)
    if (selectedCuboid) {
      const { center, dimensions, rotation } = selectedCuboid;
      const yaw = rotation?.yaw ?? 0;
      const hl = (dimensions?.length ?? 1) / 2;
      const hw = (dimensions?.width  ?? 1) / 2;
      const hh = (dimensions?.height ?? 1) / 2;
      const cos = Math.cos(yaw);
      const sin = Math.sin(yaw);
      const local: [number, number, number][] = [
        [ hl,  hw, -hh], [ hl, -hw, -hh], [-hl, -hw, -hh], [-hl,  hw, -hh],
        [ hl,  hw,  hh], [ hl, -hw,  hh], [-hl, -hw,  hh], [-hl,  hw,  hh],
      ];
      const pts = local.map(([lx, ly, lz]) =>
        project(
          center.x + cos*lx - sin*ly,
          center.y + sin*lx + cos*ly,
          center.z + lz,
        )
      );

      const edges: [number, number][] = [
        [0,1],[1,2],[2,3],[3,0],
        [4,5],[5,6],[6,7],[7,4],
        [0,4],[1,5],[2,6],[3,7],
      ];

      ctx.strokeStyle = classColor;
      ctx.lineWidth   = 2;
      ctx.globalAlpha = 1.0;
      ctx.lineCap     = 'round';

      for (const [i, j] of edges) {
        const a = pts[i];
        const b = pts[j];
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      // Fill front face (corners 0,1,5,4)
      const fc = [pts[0], pts[1], pts[5], pts[4]];
      if (fc.every(p => p !== null)) {
        ctx.fillStyle   = classColor;
        ctx.globalAlpha = 0.25;
        ctx.beginPath();
        ctx.moveTo(fc[0]!.x, fc[0]!.y);
        fc.slice(1).forEach(p => ctx.lineTo(p!.x, p!.y));
        ctx.closePath();
        ctx.fill();
      }
    } // end if (selectedCuboid)

    // Draw the clicked LiDAR point colored by depth — matches point cloud rendering style
    if (clickedPoint) {
      const { x: px, y: py, z: pz } = clickedPoint;
      const camZ = R[2][0]*px + R[2][1]*py + R[2][2]*pz + t[2];
      const ptCanvas = project(px, py, pz);
      if (ptCanvas && camZ > 0) {
        const c = Math.max(0, Math.min(255, 255 * (1 - camZ / 50.0)));
        const pointColor = `rgb(${255 - c}, 0, ${c})`;
        ctx.save();
        ctx.globalAlpha = 1.0;
        ctx.fillStyle = pointColor;
        ctx.beginPath();
        ctx.arc(ptCanvas.x, ptCanvas.y, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }
  }, [selectedCuboid, cameraCalib, containerSize, classColor, stableImageSize, useFisheyeProjection, clipBox, _imgVersion, clickedPoint, allCuboids]);

  // Auto-zoom to clicked point
  useEffect(() => {
    if (!clickedPoint || !cameraCalib || !containerSize.width || !containerSize.height) {
      if (!clickedPoint) { setZoom(1); setPan({ x: 0, y: 0 }); }
      return;
    }
    const img = imgRef.current;
    const imageWidth  = (img && img.naturalWidth  > 0) ? img.naturalWidth  : stableImageSize.width;
    const imageHeight = (img && img.naturalHeight > 0) ? img.naturalHeight : stableImageSize.height;
    const cW = containerSize.width;
    const cH = containerSize.height;

    const containerAspect = cW / cH;
    const imageAspect = imageWidth / imageHeight;
    let displayWidth: number, displayHeight: number;
    if (containerAspect > imageAspect) {
      displayHeight = cH; displayWidth = cH * imageAspect;
    } else {
      displayWidth = cW; displayHeight = cW / imageAspect;
    }
    const oX = (cW - displayWidth)  / 2;
    const oY = (cH - displayHeight) / 2;
    const scaleX = displayWidth  / imageWidth;
    const scaleY = displayHeight / imageHeight;

    const { extrinsic, intrinsic } = cameraCalib;
    const { fx, fy, cx, cy, camera_model, distortion } = intrinsic;
    const R = extrinsic.rotation;
    const t = extrinsic.translation;
    const isAutoFisheye = distortion?.length === 4 && fx < imageWidth / 2;
    const useFisheye = useFisheyeProjection || camera_model === 'kannala_brandt' || isAutoFisheye;

    const { x: px, y: py, z: pz } = clickedPoint;
    const camX = R[0][0]*px + R[0][1]*py + R[0][2]*pz + t[0];
    const camY = R[1][0]*px + R[1][1]*py + R[1][2]*pz + t[1];
    const camZ = R[2][0]*px + R[2][1]*py + R[2][2]*pz + t[2];
    if (camZ <= (useFisheye ? -1.0 : 0.1)) return;

    let u: number, v: number;
    if (useFisheye) {
      const r = Math.sqrt(camX * camX + camY * camY);
      const theta = Math.atan2(r, camZ);
      if (theta > Math.PI * 0.9) return;
      const k2 = distortion?.[0] ?? 0, k3 = distortion?.[1] ?? 0;
      const k4 = distortion?.[2] ?? 0, k5 = distortion?.[3] ?? 0;
      const th2 = theta * theta;
      const theta_d = theta * (1 + k2*th2 + k3*th2*th2 + k4*th2*th2*th2 + k5*th2*th2*th2*th2);
      const scale = r > 1e-8 ? theta_d / r : 1;
      u = fx * scale * camX + cx;
      v = fy * scale * camY + cy;
    } else {
      u = fx * camX / camZ + cx;
      v = fy * camY / camZ + cy;
    }
    if (u < 0 || u > imageWidth || v < 0 || v > imageHeight) return;

    const canvasX = u * scaleX + oX;
    const canvasY = v * scaleY + oY;

    const targetZoom = 4;
    setZoom(targetZoom);
    setPan({ x: (cW / 2 - canvasX) * targetZoom, y: (cH / 2 - canvasY) * targetZoom });
  }, [clickedPoint, containerSize, cameraCalib, stableImageSize, useFisheyeProjection, _imgVersion]);

  // Wheel zoom handler
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const factor = e.deltaY > 0 ? -1 : 1;
    setZoom(prev => factor > 0 ? Math.min(prev * 1.15, 10) : Math.max(prev / 1.15, 1));
  }, []);

  // Pan handlers
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (zoom <= 1) return;
    e.preventDefault();
    e.stopPropagation();
    isDragging.current = true;
    lastPointer.current = { x: e.clientX, y: e.clientY };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, [zoom]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return;
    e.preventDefault();
    const dx = e.clientX - lastPointer.current.x;
    const dy = e.clientY - lastPointer.current.y;
    lastPointer.current = { x: e.clientX, y: e.clientY };
    setPan(prev => ({ x: prev.x + dx, y: prev.y + dy }));
  }, []);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    if (isDragging.current) {
      isDragging.current = false;
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    }
  }, []);

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const transformStyle = {
    transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
    transformOrigin: 'center center',
  };

  return (
    <div
      ref={containerRef}
      onClick={zoom <= 1 ? onClick : undefined}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onDoubleClick={handleDoubleClick}
      className="relative rounded-lg overflow-hidden border border-gray-600 hover:border-primary transition-all cursor-pointer group bg-black flex items-center justify-center"
      style={{ cursor: zoom > 1 ? 'grab' : 'pointer' }}
    >
      {imageUrl ? (
        <>
          <img
            ref={imgRef}
            src={imageUrl}
            alt={cameraId}
            className="max-w-full max-h-full object-contain"
            style={{ ...transformStyle, pointerEvents: 'none' }}
            draggable={false}
            onLoad={() => setImgVersion(v => v + 1)}
          />

          {/* Canvas overlay — drawn by the useEffect above */}
          <canvas
            ref={canvasRef}
            className="absolute inset-0 pointer-events-none"
            style={{ ...transformStyle, width: '100%', height: '100%' }}
          />

          <div className="absolute inset-0 bg-black/10 group-hover:bg-transparent transition-colors pointer-events-none" />
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent text-white text-[10px] px-2 py-1.5 pointer-events-none">
            {cameraId.replace(/_/g, ' ')}
          </div>
          <div className="absolute top-1 right-1 w-2 h-2 rounded-full bg-green-500 shadow pointer-events-none" />
          {zoom > 1 && (
            <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-black/70 rounded text-white text-[9px] pointer-events-none">
              {Math.round(zoom * 100)}%
            </div>
          )}
        </>
      ) : (
        <div className="w-full h-full bg-dark flex flex-col items-center justify-center min-h-[60px]">
          <svg className="w-6 h-6 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
          </svg>
          <span className="text-[10px] text-gray-400 mt-1 px-1 text-center">
            {cameraId.replace(/_/g, ' ')}
          </span>
        </div>
      )}
    </div>
  );
});

export const FocusedCameraViews: React.FC<FocusedCameraViewsProps> = ({
  visibleCameras,
  selectedCuboid,
  classColor,
  panelHeight,
  onHeightChange,
  isFullWidth = false,
  orthoViewsWidth = 384,
  qaPanelOffset = 0,
  clickedPoint,
  onCameraClick,
}) => {
  const { scene, currentFrame } = useEditorStore();
  const getCachedImage = useImageCacheStore((s) => s.getCached);
  const [isResizing, setIsResizing] = useState(false);

  // Build image URL for a camera - check cache first for instant display
  // FocusedCameraCard needs full-res images so naturalWidth matches the calibration
  // intrinsic coordinate space. Thumbnails (width=600) cause projection misalignment.
  const getImageUrl = (cameraId: string): string | undefined => {
    if (!scene?.storage_paths?.cameras?.[cameraId] || !currentFrame?.file_paths?.cameras?.[cameraId]) {
      return undefined;
    }
    const basePath = scene.storage_paths.cameras[cameraId].replace(/\/$/, '');
    const filename = currentFrame.file_paths.cameras[cameraId];

    // Check cache first for instant load (no network delay)
    const cached = getCachedImage(`${basePath}/${filename}`);
    if (cached) {
      return cached; // Return cached blob URL
    }

    // Fallback to API endpoint
    const token = useAuthStore.getState().accessToken;
    const baseUrl = `/api/v1/data/image/${basePath}/${filename}`;
    const params = new URLSearchParams();
    if (token) params.append('token', token);
    // No width restriction — full-res so naturalWidth matches calibration intrinsic space
    return `${baseUrl}?${params.toString()}`;
  };

  // Current-frame cuboids for thin projections across all cameras (static review)
  const frameAnnotations = useCurrentFrameAnnotations();
  const taxonomy = useEditorStore((st) => st.taxonomy);
  const allCuboids = React.useMemo(() => {
    const hiddenIds = useEditorStore.getState().hiddenAnnotationIds;
    return frameAnnotations
      .filter((a) => a.type === 'cuboid' && !!a.data && !hiddenIds.has(a.id))
      .map((a) => {
        const def = taxonomy?.classes.find((c) => c.id === a.class_id);
        return {
          cuboid: a.data as CuboidData,
          color: def?.color || '#3b82f6',
          accepted: a.is_verified === true,
        };
      });
  }, [frameAnnotations, taxonomy, selectedCuboid]);

  // Handle resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const newHeight = window.innerHeight - e.clientY;
      onHeightChange(Math.max(120, Math.min(newHeight, 500)));
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
  }, [isResizing, onHeightChange]);

  if (visibleCameras.length === 0) return null;

  // Calculate grid layout based on number of visible cameras
  const getGridClass = () => {
    if (isFullWidth) {
      // Full width mode - use more columns for all cameras
      if (visibleCameras.length <= 2) return 'grid-cols-2';
      if (visibleCameras.length <= 4) return 'grid-cols-4';
      return 'grid-cols-4';
    }
    if (visibleCameras.length === 1) return 'grid-cols-1';
    if (visibleCameras.length === 2) return 'grid-cols-2';
    if (visibleCameras.length <= 4) return 'grid-cols-2';
    return 'grid-cols-3';
  };

  // Calculate total right offset: ortho views + QA panel (if visible)
  const totalRightOffset = (isFullWidth ? 0 : orthoViewsWidth) + qaPanelOffset;

  return (
    <div
      className="absolute bottom-0 left-0 z-20 transition-all duration-300"
      style={{ height: panelHeight, right: totalRightOffset }}
    >
      <div className="h-full bg-dark-panel/95 backdrop-blur-sm border-t border-gray-700 relative">
        {/* Resize Handle */}
        <div
          className="absolute top-0 left-0 right-0 h-1.5 cursor-ns-resize hover:bg-primary/50 z-50 group"
          onMouseDown={(e) => {
            e.preventDefault();
            setIsResizing(true);
          }}
        >
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-12 h-1 rounded-full bg-gray-600 group-hover:bg-primary transition-colors" />
        </div>

        {/* Header */}
        <div className="h-8 bg-dark-panel border-b border-gray-700 flex items-center px-3 mt-1">
          <svg className="w-4 h-4 text-primary mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
          <span className="text-xs font-medium text-white">
            {isFullWidth ? 'All Cameras' : 'Visible Cameras'} ({visibleCameras.length})
          </span>
          <span className="ml-2 text-[10px] text-gray-500">
            {isFullWidth ? 'Click a 3D box to see projected views' : 'Showing cameras where box is visible'}
          </span>
          <span className="ml-auto text-[10px] text-gray-500">Drag to resize</span>
        </div>

        {/* Camera grid - use flexbox for better aspect ratio handling */}
        <div className={`p-2 h-[calc(100%-2.5rem)] overflow-auto grid ${getGridClass()} gap-2`}>
          {visibleCameras.map((cameraId) => (
            <FocusedCameraCard
              key={cameraId}
              cameraId={cameraId}
              imageUrl={getImageUrl(cameraId)}
              selectedCuboid={selectedCuboid}
              classColor={classColor}
              onClick={() => onCameraClick ? onCameraClick(cameraId) : useEditorStore.getState().activateCameraView(cameraId)}
              clickedPoint={clickedPoint}
              allCuboids={allCuboids}
            />
          ))}
        </div>
      </div>
    </div>
  );
};
