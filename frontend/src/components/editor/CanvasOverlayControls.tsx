import React from 'react';
import { useEditorStore } from '@/store/editorStore';
import type { ViewMode } from './types';

export interface CanvasOverlayControlsProps {
  viewMode: ViewMode;
  onOpenShortcutsHelp: () => void;
  onOpenCameraImageView: (cameraId: string) => void;
}

export const CanvasOverlayControls: React.FC<CanvasOverlayControlsProps> = ({
  viewMode,
  onOpenShortcutsHelp,
  onOpenCameraImageView,
}) => {
  const lidarView = useEditorStore((s) => s.lidarView);

  if (viewMode === '2d') return null;

  return (
    <div className="absolute top-16 left-4 z-30 flex items-center gap-2">
      {/* Top View Toggle Button */}
      <button
        onClick={() => useEditorStore.getState().toggleTopView()}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium text-sm ${
          lidarView.isTopView
            ? 'bg-blue-500 text-white hover:bg-blue-600'
            : 'bg-dark-panel/90 text-gray-300 hover:bg-gray-700 border border-gray-600'
        }`}
        title={lidarView.isTopView ? 'Switch to Perspective View [Shift+T]' : 'Switch to Top/Bird\'s Eye View [Shift+T]'}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          {lidarView.isTopView ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v14a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM9 4v16M15 4v16M4 9h16M4 15h16" />
          )}
        </svg>
        {lidarView.isTopView ? '3D' : 'Top'}
      </button>

      {/* Fisheye Projection Toggle Button */}
      <button
        onClick={() => useEditorStore.getState().toggleFisheyeProjection()}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium text-sm ${
          lidarView.useFisheyeProjection
            ? 'bg-purple-500 text-white hover:bg-purple-600'
            : 'bg-dark-panel/90 text-gray-300 hover:bg-gray-700 border border-gray-600'
        }`}
        title={lidarView.useFisheyeProjection ? 'Switch to Pinhole Projection [Alt+F]' : 'Switch to Fisheye Projection [Alt+F]'}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          {lidarView.useFisheyeProjection ? (
            <>
              <circle cx="12" cy="12" r="9" strokeWidth={2} />
              <ellipse cx="12" cy="12" rx="5" ry="9" strokeWidth={1.5} />
              <ellipse cx="12" cy="12" rx="9" ry="5" strokeWidth={1.5} />
            </>
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
          )}
        </svg>
        {lidarView.useFisheyeProjection ? 'Fisheye' : 'Pinhole'}
      </button>

      {/* Ground Plane Detection Toggle Button */}
      <button
        onClick={() => useEditorStore.getState().setLidarView({
          groundPlane: {
            ...lidarView.groundPlane,
            enabled: !(lidarView.groundPlane?.enabled ?? true),
          },
        })}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-medium text-sm ${
          (lidarView.groundPlane?.enabled ?? true)
            ? 'bg-emerald-500 text-white hover:bg-emerald-600'
            : 'bg-dark-panel/90 text-gray-300 hover:bg-gray-700 border border-gray-600'
        }`}
        title={(lidarView.groundPlane?.enabled ?? true) ? 'Disable Ground Plane Detection' : 'Enable Ground Plane Detection'}
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 17h18M3 17l3-5M21 17l-3-5M9 12l3-5 3 5" />
        </svg>
        Ground
      </button>

      {/* Keyboard Shortcuts Help Button */}
      <button
        onClick={onOpenShortcutsHelp}
        className="flex items-center justify-center w-7 h-7 rounded-lg bg-dark-panel/90 text-gray-400 hover:text-white hover:bg-gray-700 border border-gray-600 transition-colors text-sm font-bold"
        title="Keyboard Shortcuts [H]"
      >
        ?
      </button>

      {/* Camera View Mode Indicator - Only show in non-4D mode */}
      {viewMode !== '4d' && lidarView.cameraView?.isActive && lidarView.cameraView?.cameraId && (
        <div className="flex items-center gap-2 ml-2 bg-primary/20 border border-primary/50 rounded-lg px-3 py-1.5">
          <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
          <span className="text-sm text-primary font-medium">
            {lidarView.cameraView.cameraId.replace(/_/g, ' ')}
          </span>

          {/* 2D Image — camera image only, no projected lidar points */}
          <button
            onClick={() => {
              const camId = lidarView.cameraView?.cameraId;
              if (camId != null) onOpenCameraImageView(camId as string);
            }}
            className={`ml-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${
              lidarView.cameraView.imageOnlyMode
                ? 'bg-green-500/60 text-green-100'
                : 'bg-green-500/20 text-green-400 hover:bg-green-500/40'
            }`}
            title="Show camera image only (no lidar points)"
          >
            2D Image
          </button>

          {/* 2D Overlay — camera image with projected lidar points */}
          {!lidarView.cameraView.frustumOnlyMode && (
            <button
              onClick={() => {
                useEditorStore.getState().setLidarView({
                  cameraView: {
                    ...lidarView.cameraView,
                    imageOnlyMode: false,
                  },
                });
              }}
              className={`ml-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                !lidarView.cameraView.imageOnlyMode
                  ? 'bg-blue-500/60 text-blue-100'
                  : 'bg-blue-500/20 text-blue-400 hover:bg-blue-500/40'
              }`}
              title="Show camera image with projected lidar points"
            >
              2D Overlay
            </button>
          )}

          {/* Toggle to Frustum 3D view */}
          <button
            onClick={() => useEditorStore.getState().toggleFrustumOnlyMode()}
            className={`ml-1 px-2 py-0.5 rounded text-xs font-medium transition-colors ${
              lidarView.cameraView.frustumOnlyMode
                ? 'bg-green-500/60 text-green-100'
                : 'bg-gray-500/20 text-gray-400 hover:bg-gray-500/40'
            }`}
            title={lidarView.cameraView.frustumOnlyMode ? 'Exit frustum view' : 'Switch to Frustum 3D View'}
          >
            3D Frustum
          </button>

          <button
            onClick={() => useEditorStore.getState().deactivateCameraView()}
            className="ml-1 p-0.5 rounded hover:bg-primary/30 text-primary/70 hover:text-primary transition-colors"
            title="Exit camera view (Esc)"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
};
