import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useEditorStore } from '@/store/editorStore';
import type { ViewMode } from './types';

export interface CuboidPlacementHintProps {
  taskId?: string;
  viewMode: ViewMode;
}

const CUBOID_HINT_BOX_LIMIT = 5;

export const CuboidPlacementHint: React.FC<CuboidPlacementHintProps> = ({ taskId, viewMode }) => {
  const activeTool = useEditorStore((s) => s.activeTool);
  const isBoxPlacementActive = useEditorStore((s) => s.isBoxPlacementActive);
  const [cuboidHintCount, setCuboidHintCount] = useState(0);
  const [cuboidHintDismissed, setCuboidHintDismissed] = useState(false);
  const [hintTimerRunning, setHintTimerRunning] = useState(false);
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    try {
      const raw = localStorage.getItem(`task_timer_${taskId}`);
      if (raw !== null) setHintTimerRunning(JSON.parse(raw).running === true);
    } catch { /* ignore */ }
  }, [taskId]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ running: boolean; taskId: string }>).detail;
      if (detail?.taskId !== taskId) return;
      setHintTimerRunning(detail.running);
      if (!detail.running) {
        const st = useEditorStore.getState();
        if (st.activeTool === 'cuboid' || st.activeTool === 'track') {
          st.setBoxPlacementActive(false);
          st.setActiveTool('select');
        }
      }
    };
    window.addEventListener('timerStateChange', handler);
    return () => window.removeEventListener('timerStateChange', handler);
  }, [taskId]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ open: boolean }>).detail;
      setLeaveDialogOpen(Boolean(detail?.open));
    };
    window.addEventListener('editorLeaveDialogChange', handler);
    return () => window.removeEventListener('editorLeaveDialogChange', handler);
  }, []);

  const showCuboidHint =
    hintTimerRunning &&
    !leaveDialogOpen &&
    !cuboidHintDismissed &&
    cuboidHintCount < CUBOID_HINT_BOX_LIMIT;

  const dismissCuboidHint = useCallback(() => setCuboidHintDismissed(true), []);

  const placementStartSizeRef = useRef(0);
  const wasPlacingRef = useRef(false);

  useEffect(() => {
    setCuboidHintCount(0);
    setCuboidHintDismissed(false);
    wasPlacingRef.current = false;
  }, [taskId]);

  useEffect(() => {
    if (isBoxPlacementActive && !wasPlacingRef.current) {
      wasPlacingRef.current = true;
      placementStartSizeRef.current = useEditorStore.getState().annotations.size;
    } else if (!isBoxPlacementActive && wasPlacingRef.current) {
      wasPlacingRef.current = false;
      const endSize = useEditorStore.getState().annotations.size;
      if (endSize > placementStartSizeRef.current && showCuboidHint) {
        setCuboidHintCount((c) => c + 1);
      }
    }
  }, [isBoxPlacementActive, showCuboidHint]);

  if (viewMode === '2d' || (activeTool !== 'cuboid' && activeTool !== 'track') || !showCuboidHint) {
    return null;
  }

  return (
    <div className="absolute top-28 left-4 z-[100] animate-fadeInDown">
      <div className="flex items-center gap-2 pl-2.5 pr-1.5 py-1.5 rounded-xl bg-gray-950/95 border border-amber-500/50 shadow-[0_0_0_1px_rgba(245,158,11,0.15),0_4px_16px_rgba(0,0,0,0.6)]">
        <span className="flex-shrink-0 w-5 h-5 rounded-full bg-amber-500/15 border border-amber-500/40 flex items-center justify-center">
          <svg className="w-3 h-3 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </span>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-300 whitespace-nowrap">
            <span className="text-white font-semibold">Shift+drag</span> to start
          </span>
          <span className="text-gray-600">→</span>
          <span className="text-[10px] text-gray-300 whitespace-nowrap">
            hold Shift to <span className="text-orange-400 font-semibold">steer</span>
          </span>
          <span className="text-gray-400 font-semibold" title="Toggle Shift to switch back and forth">⇄</span>
          <span className="text-[10px] text-gray-300 whitespace-nowrap">
            release to <span className="text-green-400 font-semibold">slide</span>
          </span>
          <span className="text-gray-600">→</span>
          <span className="text-[10px] text-gray-300 whitespace-nowrap">
            <span className="text-white font-semibold">mouse-up</span> to drop
          </span>
        </div>
        <button
          onClick={dismissCuboidHint}
          title="Got it — don't show again"
          aria-label="Dismiss hint"
          className="flex-shrink-0 ml-0.5 w-5 h-5 rounded flex items-center justify-center text-gray-500 hover:text-white hover:bg-white/10 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
};
