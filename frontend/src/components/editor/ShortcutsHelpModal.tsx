import React from 'react';
import type { ViewMode } from './types';

export interface ShortcutsHelpModalProps {
  isOpen: boolean;
  onClose: () => void;
  viewMode: ViewMode;
  effectiveQAMode: boolean;
}

/**
 * Dated shortcut changelog shown at the top of this dialog. Keep the newest
 * entry first; the key list below stays the single source of truth for the
 * full mapping.
 */
const RECENT_UPDATES: Array<{ date: string; items: Array<[string, string]> }> = [
  {
    date: '2026-10-28',
    items: [
      ['N', '跳到下一个未确认框（本帧内循环）'],
      ['Shift+N', '跳到下一帧的第一个未确认框'],
      ['Shift+V', '确认当前框并跳到下一个（已确认则直接跳）'],
    ],
  },
];

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
          {/* Dated changelog */}
          {RECENT_UPDATES.map((entry) => (
            <div
              key={entry.date}
              className="mb-5 rounded-lg border border-emerald-500/30 bg-emerald-500/[0.07] px-4 py-3"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-semibold tracking-wider text-emerald-300">
                  NEW
                </span>
                <span className="text-xs font-semibold text-emerald-200">
                  {entry.date} 更新
                </span>
              </div>
              <div className="space-y-1">
                {entry.items.map(([key, desc]) => (
                  <div key={key} className="flex items-center justify-between py-0.5">
                    <span className="text-xs text-gray-300">{desc}</span>
                    <kbd className="px-1.5 py-0.5 bg-dark border border-emerald-600/50 rounded text-[10px] font-mono text-emerald-300">
                      {key}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          ))}

          <div className="grid grid-cols-2 gap-6">

            {/* Left Column */}
            <div className="space-y-5">
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
                    ['Ctrl+Y / Ctrl+Shift+Z', 'Redo'],
                    ['Del / ⌫', 'Delete selected'],
                    ['Esc', 'Cancel / Deselect'],
                    ['1-9, 0, 10+', 'Quick class select (supports multi-digit)'],
                    ['H', 'Toggle this help'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-blue-300">{key}</kbd>
                    </div>
                  ))}
                </div>
              </div>

              {/* Navigation */}
              <div>
                <h3 className="text-sm font-semibold text-indigo-400 mb-3 flex items-center gap-2">
                  <span className="w-5 h-5 rounded bg-indigo-500/20 flex items-center justify-center">🎞️</span>
                  Navigation
                </h3>
                <div className="space-y-1.5">
                  {[
                    ['F / B', 'Next / Prev frame'],
                    ['← →', 'Prev / Next frame (when no box selected)'],
                    ['Alt + ← →', 'Force frame step (even with box selected)'],
                    ['Shift + ← →', 'Step one frame forward / backward'],
                    ['Home / End', 'Jump to first / last frame'],
                  ].map(([key, desc]) => (
                    <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                      <span className="text-xs text-gray-400">{desc}</span>
                      <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-indigo-300">{key}</kbd>
                    </div>
                  ))}
                </div>
              </div>

              {/* Camera & View Controls (3D) */}
              {viewMode !== '2d' && (
                <div>
                  <h3 className="text-sm font-semibold text-cyan-400 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-cyan-500/20 flex items-center justify-center">🎥</span>
                    Camera & View
                  </h3>
                  <div className="space-y-1.5">
                    {[
                      ['Shift+T', 'Toggle top view (BEV)'],
                      ['Alt + F', 'Toggle fisheye / pinhole projection'],
                      ['G', 'Reset camera (return to 3D perspective)'],
                      ['Dbl-Click Box', 'Focus camera on selected box'],
                    ].map(([key, desc]) => (
                      <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                        <span className="text-xs text-gray-400">{desc}</span>
                        <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-cyan-300">{key}</kbd>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 2D Annotation Shortcuts — only relevant in 2D mode */}
            {viewMode === '2d' && (
              <div className="space-y-5">
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
                </div>

                <div>
                  <h4 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-green-500/20 flex items-center justify-center">✏️</span>
                    Drawing
                  </h4>
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
                </div>

                <div>
                  <h4 className="text-sm font-semibold text-green-400 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-green-500/20 flex items-center justify-center">✂️</span>
                    Segment Editing
                  </h4>
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
              </div>
            )}

            {/* 3D Annotation Shortcuts — only relevant in 3D / fusion / 4D modes */}
            {viewMode !== '2d' && (
              <div className="space-y-5">
                <div>
                  <h3 className="text-sm font-semibold text-purple-400 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-purple-500/20 flex items-center justify-center">📦</span>
                    3D Tools
                  </h3>
                  <div className="space-y-1.5">
                    {[
                      ['C', 'Cuboid tool'],
                      ['T', 'Track tool (multi-frame track)'],
                      ['S', '3D Brush tool (when unselected)'],
                      ['V', 'Accept / Unaccept（核验合格切换）'],
                      ['Shift+V', '确认当前框并跳到下一个（已确认则直接跳） · NEW'],
                      ['N', '跳到下一个未确认框（本帧循环） · NEW'],
                      ['Shift+N', '跳到下一帧的第一个未确认框 · NEW'],
                      ['Shift+Click', 'Draw box (select mode)'],
                    ].map(([key, desc]) => (
                      <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                        <span className="text-xs text-gray-400">{desc}</span>
                        <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-purple-300">{key}</kbd>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-semibold text-purple-400 mb-3 flex items-center gap-2">
                    <span className="w-5 h-5 rounded bg-purple-500/20 flex items-center justify-center">📐</span>
                    Box Editing
                  </h4>
                  <div className="space-y-1.5">
                    {[
                      ['Q / E', 'Rotate left / right (Shift: 1° fine)'],
                      ['R', 'Reset rotation to 0'],
                      ['W / S', '垂直移动受控边（光标在上半区调上边，在下半区调下边，对边固定；按住 Alt 为中心缩放；Shift: 0.01m 微调）'],
                      ['A / D', '水平移动受控边（光标在左半区调左边，在右半区调右边，对边固定；按住 Alt 为中心缩放；Shift: 0.01m 微调）'],
                      ['Z / X', '视口垂直深度轴 伸展 / 缩短（中心对称；Shift: 0.01m 微调）'],
                      ['边框点击', '点击正交视图单侧边框可临时锁定/解锁该边，锁定后专控该边'],
                      ['← → ↑ ↓', '框体平移移动（各正交视口及 3D 自适应，步长 0.1m）'],
                      ['Shift + 方向键', '框体微调移动（每次 0.01m 毫米级位移，各视口自适应）'],
                      ['Alt + +/-', 'Uniform scale box (ortho panel)'],
                      ['Ctrl+D', 'Duplicate selected box'],
                    ].map(([key, desc]) => (
                      <div key={key} className="flex items-center justify-between py-1 px-2 rounded hover:bg-dark/40">
                        <span className="text-xs text-gray-400">{desc}</span>
                        <kbd className="px-1.5 py-0.5 bg-dark border border-gray-600 rounded text-[10px] font-mono text-purple-300">{key}</kbd>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-gray-500 mt-2 px-2">
                    💡 单侧微调特性：鼠标在正交视图（Top/Side/Front）中靠近或指向某半区时，对应边框高亮（青色），按 W/S 或 A/D 仅单侧边框位移，对边完全固定不动！点击边框可锁定（粉色）。按住 Alt 键恢复中心对称缩放。
                  </p>
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
