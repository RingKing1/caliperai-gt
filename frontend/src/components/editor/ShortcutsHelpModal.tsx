import React from 'react';
import type { ViewMode } from './types';

export interface ShortcutsHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
  viewMode: ViewMode;
  effectiveQAMode: boolean;
}

export const ShortcutsHelpModal: React.FC<ShortcutsHelpModalProps> = ({
  isOpen,
  onClose,
  viewMode,
  effectiveQAMode,
}) => {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-dark-panel border border-gray-600 rounded-xl shadow-2xl max-w-4xl w-full mx-4 overflow-hidden max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-600/20 to-purple-600/20 border-b border-gray-600 px-6 py-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-white">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 overflow-y-auto">
          <div className="grid grid-cols-2 gap-6">

            {/* Common Shortcuts */}
            <div>
              <h3 className="text-sm font-semibold text-blue-400 mb-3 flex items-center gap-2">
                <span className="w-5 h-5 rounded bg-blue-500/20 flex items-center justify-center">⌨️</span>
                Common
              </h3>
              <div className="space-y-1.5">
                {[
                  ['Ctrl+S', 'Save annotations'],
                  ['Ctrl+Z', 'Undo'],
                  ['Ctrl+Y', 'Redo'],
                  ['Del / ⌫', 'Delete selected'],
                  ['Esc', 'Cancel / Deselect'],
                  ['1-9, 0, 10+', 'Quick class select'],
                  ['H', 'Toggle this help'],
                ].map(([key, desc]) => (
                  <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                    <span className="text-xs text-gray-400">{desc}</span>
                    <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-blue-300">{key}</kbd>
                  </div>
                ))}
              </div>
            </div>

            {/* 2D Annotation Shortcuts — only relevant in 2D mode */}
            {viewMode === '2d' && (
              <div>
                <h3 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
                  <span className="w-5 h-5 rounded bg-green-500/20 flex items-center justify-center">🖼️</span>
                  2D Tools
                </h3>
                <div className="space-y-1.5">
                  {[
                    ['V', 'Select tool'],
                    ['Space', 'Pan (hold + drag)'],
                    ['R', 'Rectangle'],
                    ['E', 'Ellipse'],
                    ['P', 'Polygon'],
                    ['L', 'Polyline'],
                    ['K', 'Points'],
                    ['W', 'AI Segmentation'],
                    ['M', 'AI Polygon'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-green-300">{key}</kbd>
                    </div>
                  ))}
                </div>

                <h4 className="text-xs font-medium text-gray-500 mt-3 mb-1.5">Drawing</h4>
                <div className="space-y-1.5">
                  {[
                    ['Enter', 'Complete shape'],
                    ['Backspace', 'Undo last point'],
                    ['Dbl-Click', 'Fit to window'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-green-300">{key}</kbd>
                    </div>
                  ))}
                </div>

                <h4 className="text-xs font-medium text-gray-500 mt-3 mb-1.5">Segment Editing</h4>
                <div className="space-y-1.5">
                  {[
                    ['Shift + Left Click', 'Add point to segment'],
                    ['Shift + Right Click', 'Delete point from segment'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-green-300">{key}</kbd>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 3D Annotation Shortcuts — only relevant in 3D / fusion / 4D modes */}
            {viewMode !== '2d' && (
              <div>
                <h3 className="text-sm font-semibold text-purple-400 mb-3 flex items-center gap-2">
                  <span className="w-5 h-5 rounded bg-purple-500/20 flex items-center justify-center">📦</span>
                  3D Tools
                </h3>
                <div className="space-y-1.5">
                  {[
                    ['C', 'Cuboid tool'],
                    ['T', 'Track tool'],
                    ['Shift+Click', 'Draw box (select mode)'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-purple-300">{key}</kbd>
                    </div>
                  ))}
                </div>

                <h4 className="text-xs font-medium text-gray-500 mt-3 mb-1.5">Box Editing</h4>
                <div className="space-y-1.5">
                  {[
                    ['Q / E', 'Rotate left / right'],
                    ['R', 'Reset rotation'],
                    ['W / S', 'Grow / Shrink length'],
                    ['A / D', 'Grow / Shrink width'],
                    ['Z / X', 'Grow / Shrink height'],
                    ['← → ↑ ↓', 'Move box (view-aware in active ortho panel)'],
                    ['Shift + Arrows', 'Fine move (3D view) / Rotate (ortho panel)'],
                    ['Ctrl+D', 'Duplicate'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-purple-300">{key}</kbd>
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-gray-500 mt-1.5 px-2">
                  Ortho mapping: Top (X/Y), Front (X/Z), Side (Y/Z). Click or hover a panel to make it active for arrow movement.
                </p>

                <h4 className="text-xs font-medium text-gray-500 mt-3 mb-1.5">Navigation</h4>
                <div className="space-y-1.5">
                  {[
                    ['F / B', 'Next / Prev frame'],
                    ['← →', 'Prev / Next frame (when no box selected)'],
                    ['Alt + ← →', 'Force frame step (even with box selected)'],
                    ['Shift+T', 'Toggle top view'],
                    ['Alt + F', 'Toggle fisheye projection'],
                    ['G', 'Back to 3D view'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-purple-300">{key}</kbd>
                    </div>
                  ))}
                </div>
              </div>
            )}

          </div>

          {/* Mouse Controls Row */}
          <div className="mt-5 pt-4 border-t border-gray-700">
            <h3 className="text-sm font-semibold text-gray-400 mb-3">Mouse Controls</h3>
            <div className="grid grid-cols-4 gap-3">
              <div className="text-center p-2 rounded bg-dark/30">
                <div className="text-xs font-medium text-gray-300 mb-1">Left Drag</div>
                <div className="text-[10px] text-gray-500">Rotate 3D / Select 2D</div>
              </div>
              <div className="text-center p-2 rounded bg-dark/30">
                <div className="text-xs font-medium text-gray-300 mb-1">Right Drag</div>
                <div className="text-[10px] text-gray-500">Pan view</div>
              </div>
              <div className="text-center p-2 rounded bg-dark/30">
                <div className="text-xs font-medium text-gray-300 mb-1">Middle Drag</div>
                <div className="text-[10px] text-gray-500">Pan view</div>
              </div>
              <div className="text-center p-2 rounded bg-dark/30">
                <div className="text-xs font-medium text-gray-300 mb-1">Scroll</div>
                <div className="text-[10px] text-gray-500">Zoom in / out</div>
              </div>
            </div>
          </div>

          {/* QA Mode */}
          {effectiveQAMode && (
            <div className="mt-5 pt-4 border-t border-gray-700">
              <h3 className="text-sm font-semibold text-yellow-400 mb-3 flex items-center gap-2">
                <span className="w-5 h-5 rounded bg-yellow-500/20 flex items-center justify-center">🔍</span>
                QA Review
              </h3>
              <div className="grid grid-cols-4 gap-3">
                {[
                  ['1', 'Approve'],
                  ['2', 'Reject'],
                  ['3', 'Flag'],
                  ['Shift+F', 'Flag missing'],
                ].map(([key, desc]) => (
                  <div key={key} className="flex items-center justify-between py-1.5 px-3 rounded bg-yellow-500/10 border border-yellow-600/30">
                    <span className="text-xs text-gray-300">{desc}</span>
                    <kbd className="px-1.5 py-0.5 bg-dark border border-yellow-700 rounded text-[10px] font-mono text-yellow-300">{key}</kbd>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-dark/50 border-t border-gray-700 shrink-0">
          <p className="text-xs text-gray-500 text-center">
            Press <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-xs font-mono text-gray-400">H</kbd> or <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-xs font-mono text-gray-400">Esc</kbd> to close
          </p>
        </div>
      </div>
    </div>
  );
};
