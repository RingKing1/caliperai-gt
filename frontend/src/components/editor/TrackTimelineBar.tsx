import React, { useRef, useEffect, useState, useCallback } from 'react';
import { useTrackTimeline } from '@/hooks/useTrackTimeline';

export const TrackTimelineBar: React.FC = () => {
  const {
    isOpen,
    closeTimeline,
    switchTrack,
    isLoading,
    activeTrackId,
    currentClassId,
    selectedOtherTrackId,
    timelineNodes,
    trackedCount,
    totalNodesCount,
    currentFrameDisplayNumber,
    isCurrentFrameTracked,
    keyframeSamplingEnabled,
    keyframeInterval,
    candidateToLink,
    baselineDimensions,
    jumpToFrame,
    jumpToTrackStart,
    jumpToTrackEnd,
    addToTrack,
    detachFromTrack,
    mergeWithTrack,
    syncDimensions,
  } = useTrackTimeline();

  const containerRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const currentNodeRef = useRef<HTMLButtonElement>(null);

  // Drag-to-move state
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{
    startX: number;
    startY: number;
    initialLeft: number;
    initialTop: number;
  } | null>(null);

  // Minimized capsule state
  const [isMinimized, setIsMinimized] = useState(false);

  // Modals & Action states
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [showDetachModal, setShowDetachModal] = useState(false);

  const [isSyncing, setIsSyncing] = useState(false);
  const [isLinking, setIsLinking] = useState(false);
  const [isDetaching, setIsDetaching] = useState(false);
  const [isMerging, setIsMerging] = useState(false);

  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Handle Dragging
  const handleDragStart = (e: React.MouseEvent) => {
    // Left-click only
    if (e.button !== 0) return;
    // Don't drag if clicking buttons or inputs
    const target = e.target as HTMLElement;
    if (target.closest('button') || target.closest('input')) return;

    if (!containerRef.current) return;
    e.preventDefault();

    const rect = containerRef.current.getBoundingClientRect();
    dragStartRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initialLeft: rect.left,
      initialTop: rect.top,
    };
    setIsDragging(true);
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragStartRef.current || !containerRef.current) return;
      const dx = e.clientX - dragStartRef.current.startX;
      const dy = e.clientY - dragStartRef.current.startY;
      const newLeft = dragStartRef.current.initialLeft + dx;
      const newTop = dragStartRef.current.initialTop + dy;

      const rect = containerRef.current.getBoundingClientRect();
      const clampedX = Math.max(10, Math.min(window.innerWidth - rect.width - 10, newLeft));
      const clampedY = Math.max(10, Math.min(window.innerHeight - rect.height - 10, newTop));

      setPosition({ x: clampedX, y: clampedY });
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      dragStartRef.current = null;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  // Auto-scroll the current active frame node to the center of the timeline
  useEffect(() => {
    if (currentNodeRef.current && scrollContainerRef.current && !isMinimized) {
      currentNodeRef.current.scrollIntoView({
        behavior: 'smooth',
        inline: 'center',
        block: 'nearest',
      });
    }
  }, [timelineNodes, isMinimized]);

  // Convert vertical mouse wheel into horizontal scroll on timeline track
  const handleWheel = (e: React.WheelEvent) => {
    if (scrollContainerRef.current) {
      if (Math.abs(e.deltaX) < Math.abs(e.deltaY)) {
        scrollContainerRef.current.scrollLeft += e.deltaY;
      }
    }
  };

  const handleScrollLeft = () => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollBy({ left: -240, behavior: 'smooth' });
    }
  };

  const handleScrollRight = () => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollBy({ left: 240, behavior: 'smooth' });
    }
  };

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3800);
  }, []);

  // Handle sync dimensions execution
  const handleConfirmSync = async () => {
    if (!baselineDimensions) return;
    setIsSyncing(true);
    const result = await syncDimensions(baselineDimensions);
    setIsSyncing(false);
    setShowSyncModal(false);
    if (result.success) {
      showToast(
        `成功将轨迹上 ${result.count} 个物体的尺寸统一为: ${baselineDimensions.length.toFixed(2)}m × ${baselineDimensions.width.toFixed(2)}m × ${baselineDimensions.height.toFixed(2)}m`
      );
    } else {
      showToast('统一尺寸失败，请检查网络或后端日志');
    }
  };

  // Handle add candidate to track
  const handleAddToTrack = async () => {
    if (!candidateToLink) return;
    setIsLinking(true);
    const ok = await addToTrack(candidateToLink.id);
    setIsLinking(false);
    if (ok) {
      showToast(`已成功将当前帧目标加入 Track #${shortTrackId}！`);
    } else {
      showToast('加入轨迹失败，请重试');
    }
  };

  // Handle detach / split execution
  const handleConfirmDetach = async (mode: 'untrack' | 'split') => {
    setIsDetaching(true);
    const res = await detachFromTrack(undefined, mode);
    setIsDetaching(false);
    setShowDetachModal(false);
    if (res.success) {
      if (mode === 'untrack') {
        showToast(`已将当前帧从 Track #${shortTrackId} 移出 (设为未跟踪)`);
      } else {
        const shortNew = res.newTrackId ? res.newTrackId.replace(/-/g, '').slice(0, 6).toUpperCase() : 'NEW';
        showToast(`已将当前帧目标拆分为新独立轨迹 (Track #${shortNew})`);
      }
    } else {
      showToast('操作失败，请重试');
    }
  };

  // Handle merge tracks execution
  const handleConfirmMerge = async () => {
    if (!selectedOtherTrackId) return;
    setIsMerging(true);
    const shortOther = selectedOtherTrackId.replace(/-/g, '').slice(0, 6).toUpperCase();
    const res = await mergeWithTrack(selectedOtherTrackId);
    setIsMerging(false);
    if (res.success) {
      if (res.conflictCount && res.conflictCount > 0) {
        showToast(
          `已成功缝合！并入 ${res.mergedCount} 帧 (检测到 ${res.conflictCount} 帧冲突，已以主轨迹为准保留，次轨迹重叠框已完整保留原 ID 供后续合并)`
        );
      } else {
        showToast(
          `已成功将 Track #${shortOther} 的 ${res.mergedCount} 个标注全部缝合合并入当前 Track #${shortTrackId}！`
        );
      }
    } else {
      showToast('轨迹合并失败，请检查网络或后端日志');
    }
  };

  // If no track is active or user closed the bar, do not render
  if (!activeTrackId || !isOpen) {
    return null;
  }

  const shortTrackId = activeTrackId.replace(/-/g, '').slice(0, 6).toUpperCase();
  const shortOtherTrackId = selectedOtherTrackId
    ? selectedOtherTrackId.replace(/-/g, '').slice(0, 6).toUpperCase()
    : null;

  // Position styles: defaults to safely above bottom cameras/timeline (bottom: 210px)
  const containerStyle: React.CSSProperties = position
    ? {
        position: 'fixed',
        left: `${position.x}px`,
        top: `${position.y}px`,
        transform: 'none',
        zIndex: 45,
      }
    : {
        position: 'fixed',
        bottom: '210px',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 45,
      };

  // ── 1. Minimized Floating Capsule Mode ──
  if (isMinimized) {
    return (
      <div
        ref={containerRef}
        style={containerStyle}
        className="select-none transition-shadow"
        data-tour="track-timeline-minimized"
      >
        <div className="flex items-center gap-2.5 px-3.5 py-1.5 bg-gray-950/90 hover:bg-gray-900/95 border border-amber-400/50 rounded-full shadow-2xl shadow-black/80 backdrop-blur-2xl text-white">
          {/* Drag Handle */}
          <div
            className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-white px-1 py-0.5 rounded transition-colors text-xs font-mono select-none"
            title="按住拖拽移动位置"
            onMouseDown={handleDragStart}
          >
            ⋮⋮
          </div>

          {/* Track Indicator */}
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          <span className="font-bold text-xs text-amber-300">Track #{shortTrackId}</span>
          <span className="px-1.5 py-0.2 text-[10px] font-semibold rounded bg-white/10 text-cyan-200 border border-cyan-400/20">
            {currentClassId}
          </span>

          <span className="text-[11px] text-gray-300">
            已追踪 <strong className="text-amber-300">{trackedCount}</strong> 帧
          </span>

          <span className="text-gray-600">|</span>

          {/* Current Frame Status */}
          <span
            className={`text-[11px] font-mono ${
              isCurrentFrameTracked ? 'text-amber-400 font-semibold' : 'text-gray-400'
            }`}
          >
            帧 #{currentFrameDisplayNumber} ({isCurrentFrameTracked ? 'TRACK' : 'MISS'})
          </span>

          {/* Expand Button */}
          <button
            onClick={() => setIsMinimized(false)}
            className="px-2 py-0.5 text-xs text-amber-300 hover:text-amber-100 hover:bg-amber-400/20 rounded-md font-medium transition-colors flex items-center gap-1 ml-1"
            title="展开完整轨迹时间线"
          >
            展开 ▾
          </button>

          {/* Close Button */}
          <button
            onClick={closeTimeline}
            className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors ml-0.5"
            title="关闭轨迹时间线"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    );
  }

  // ── 2. Full Timeline Bar ──
  return (
    <>
      <div
        ref={containerRef}
        style={containerStyle}
        className="max-w-5xl w-[92vw] select-none"
        data-tour="track-timeline"
      >
        <div className="bg-gray-950/95 backdrop-blur-2xl border border-white/15 rounded-2xl shadow-2xl shadow-black/85 p-3 text-white flex flex-col gap-2.5 transition-all">
          
          {/* ── Top Header Bar (Draggable) ── */}
          <div
            className="flex items-center justify-between gap-3 border-b border-white/10 pb-2 cursor-grab active:cursor-grabbing"
            onMouseDown={handleDragStart}
            title="按住拖拽移动整个面板位置 (双击重置居中)"
            onDoubleClick={() => setPosition(null)}
          >
            <div className="flex items-center gap-2.5">
              {/* Drag Handle Icon */}
              <div
                className="text-gray-400 hover:text-white px-1 py-0.5 rounded hover:bg-white/10 transition-colors font-mono text-sm"
                title="按住拖拽移动面板"
              >
                ⋮⋮
              </div>

              {/* Track Badge */}
              <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-400/20 border border-amber-400/40 text-amber-300">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span className="font-bold text-xs">Track #{shortTrackId}</span>
              </div>

              {/* Class Pill */}
              <span className="px-2 py-0.5 text-[11px] font-semibold rounded bg-white/10 text-cyan-200 border border-cyan-400/20">
                {currentClassId}
              </span>

              {/* Mode indicator */}
              <div className="flex items-center gap-1 text-[11px] text-gray-400 ml-1">
                {keyframeSamplingEnabled ? (
                  <span className="flex items-center gap-1 text-amber-300 font-medium">
                    <span className="w-1.5 h-1.5 rotate-45 bg-amber-400" />
                    关键帧模式 (每{keyframeInterval}帧)
                  </span>
                ) : (
                  <span className="text-gray-400 font-medium">普通帧模式 (连续帧)</span>
                )}
                <span>·</span>
                <span>
                  已追踪 <strong className="text-amber-300">{trackedCount}</strong> 帧 / 视窗 {totalNodesCount} 帧
                </span>
                {isLoading && (
                  <span className="ml-1 w-2 h-2 rounded-full bg-cyan-400 animate-ping inline-block" />
                )}
              </div>
            </div>

            {/* Quick Actions */}
            <div className="flex items-center gap-2" onMouseDown={(e) => e.stopPropagation()}>
              <button
                onClick={jumpToTrackStart}
                className="px-2 py-1 text-[10px] bg-white/5 hover:bg-white/15 text-gray-300 hover:text-white rounded-lg transition-colors flex items-center gap-1 border border-white/10"
                title="跳转到此轨迹最早出现的帧"
              >
                ◀ 轨迹起点
              </button>

              <button
                onClick={jumpToTrackEnd}
                className="px-2 py-1 text-[10px] bg-white/5 hover:bg-white/15 text-gray-300 hover:text-white rounded-lg transition-colors flex items-center gap-1 border border-white/10"
                title="跳转到此轨迹最晚出现的帧"
              >
                轨迹终点 ▶
              </button>

              {/* Detach / Fix Button for Tracked Frame */}
              {isCurrentFrameTracked && (
                <button
                  onClick={() => setShowDetachModal(true)}
                  className="px-2.5 py-1 text-[10px] font-semibold bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/35 rounded-lg transition-all flex items-center gap-1"
                  title="当前帧若发生误跟或错标，点击从此轨迹中移出或拆分"
                >
                  <svg className="w-3 h-3 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  修改/移出此帧
                </button>
              )}

              {/* Sync Dimensions Button */}
              {baselineDimensions && (
                <button
                  onClick={() => setShowSyncModal(true)}
                  className="px-2.5 py-1 text-[10px] font-semibold bg-gradient-to-r from-blue-600/80 to-cyan-600/80 hover:from-blue-500 hover:to-cyan-500 text-white rounded-lg transition-all shadow-md shadow-cyan-900/40 flex items-center gap-1 border border-cyan-400/40"
                  title="以当前物体尺寸为基准，一键统一该 Track 线上所有帧的尺寸"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
                    />
                  </svg>
                  一键统一尺寸
                </button>
              )}

              {/* Reset Position Button (visible when dragged away from default) */}
              {position && (
                <button
                  onClick={() => setPosition(null)}
                  className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                  title="重置面板到默认居中位置"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </button>
              )}

              {/* Minimize to Capsule Button */}
              <button
                onClick={() => setIsMinimized(true)}
                className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                title="最小化为浮动胶囊 (不挡视线)"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 12H5" />
                </svg>
              </button>

              {/* Close Button */}
              <button
                onClick={closeTimeline}
                className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors ml-0.5"
                title="关闭轨迹时间线"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* ── Middle Horizontal Timeline Track ── */}
          <div className="relative flex items-center group">
            {/* Scroll Left Button */}
            <button
              onClick={handleScrollLeft}
              className="absolute left-0 z-10 w-6 h-9 bg-gray-950/80 hover:bg-gray-800 text-white/60 hover:text-white flex items-center justify-center rounded-l-lg border-y border-l border-white/10 backdrop-blur-md transition-opacity opacity-0 group-hover:opacity-100"
              title="向左滚动"
            >
              ‹
            </button>

            {/* Nodes Container */}
            <div
              ref={scrollContainerRef}
              onWheel={handleWheel}
              className="w-full flex items-center gap-1.5 py-1 px-4 overflow-x-auto scroll-smooth"
              style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
            >
              {timelineNodes.map((node) => {
                const isCurrent = node.isCurrent;
                const isTracked = node.isTracked;

                return (
                  <button
                    key={`node-${node.frameIndex}`}
                    ref={isCurrent ? currentNodeRef : undefined}
                    onClick={() => jumpToFrame(node.frameIndex)}
                    className={`flex-shrink-0 flex flex-col items-center justify-center rounded-lg transition-all duration-150 relative ${
                      isCurrent ? 'ring-2 ring-cyan-400 ring-offset-2 ring-offset-gray-950 scale-110 z-10 shadow-lg shadow-cyan-500/20' : ''
                    } ${
                      isTracked
                        ? 'bg-amber-400 hover:bg-amber-300 text-gray-950 font-bold shadow-sm shadow-amber-500/30'
                        : 'bg-gray-800/90 hover:bg-gray-700 text-gray-400 border border-gray-700/60'
                    } ${
                      keyframeSamplingEnabled ? 'w-10 h-10' : 'w-8 h-9 text-[10px]'
                    }`}
                    title={`帧 #${node.displayNumber} ${
                      node.isKeyframe ? '[关键帧]' : ''
                    } - ${isTracked ? '已追踪此物体 (点击跳转并高亮)' : '缺失追踪 (点击跳转此帧补齐或合并)'}`}
                  >
                    <span className="font-mono leading-none">{node.displayNumber}</span>
                    <span
                      className={`text-[8.5px] uppercase font-semibold mt-0.5 tracking-tight ${
                        isTracked ? 'text-amber-950' : 'text-gray-500'
                      }`}
                    >
                      {isTracked ? 'TRACK' : 'MISS'}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Scroll Right Button */}
            <button
              onClick={handleScrollRight}
              className="absolute right-0 z-10 w-6 h-9 bg-gray-950/80 hover:bg-gray-800 text-white/60 hover:text-white flex items-center justify-center rounded-r-lg border-y border-r border-white/10 backdrop-blur-md transition-opacity opacity-0 group-hover:opacity-100"
              title="向右滚动"
            >
              ›
            </button>
          </div>

          {/* ── Contextual Action Bar ── */}

          {/* CASE A: Selected object belongs to ANOTHER track -> Merge / Link / Switch */}
          {selectedOtherTrackId && candidateToLink ? (
            <div className="flex items-center justify-between px-3.5 py-2 bg-gradient-to-r from-purple-950/80 via-indigo-950/80 to-blue-950/80 border border-purple-400/40 rounded-xl text-xs text-purple-200 animate-fadeIn shadow-lg shadow-purple-950/40">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-purple-400 animate-ping" />
                <span>
                  当前帧选中目标 <strong>[{candidateToLink.class_id || 'Object'}]</strong> 归属于次轨迹{' '}
                  <strong className="text-amber-300">#{shortOtherTrackId}</strong>
                </span>
              </div>

              <div className="flex items-center gap-2">
                {/* Stitch & Merge Tracks (Direct 1-click execution) */}
                <button
                  onClick={handleConfirmMerge}
                  disabled={isMerging}
                  className="px-3.5 py-1 bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-400 hover:to-indigo-500 text-white font-bold rounded-lg transition-all flex items-center gap-1.5 shadow-md shadow-purple-500/30 active:scale-95 disabled:opacity-50"
                  title="一键将次轨迹全线所有帧合并入当前主轨迹 (以主轨迹为准，保留重叠框)"
                >
                  {isMerging ? (
                    <>
                      <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      正在缝合并入...
                    </>
                  ) : (
                    <>
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                      </svg>
                      🔗 一键缝合并入 (Merge)
                    </>
                  )}
                </button>

                {/* Only Reassign this single frame */}
                <button
                  onClick={handleAddToTrack}
                  disabled={isLinking}
                  className="px-2.5 py-1 bg-white/10 hover:bg-white/20 text-gray-200 rounded-lg transition-colors text-[11px]"
                  title="仅将当前这一帧的物体改绑至当前 Track"
                >
                  仅改绑此帧
                </button>

                {/* Switch view to other track */}
                <button
                  onClick={() => switchTrack(selectedOtherTrackId)}
                  className="px-2 py-1 bg-white/5 hover:bg-white/15 text-gray-400 hover:text-white rounded-lg transition-colors text-[11px]"
                  title="切换查看该物体的轨迹时间线"
                >
                  查看该轨迹 ↗
                </button>
              </div>
            </div>
          ) : candidateToLink ? (
            /* CASE B: Selected object has NO track yet -> Add to track */
            <div className="flex items-center justify-between px-3.5 py-1.5 bg-gradient-to-r from-cyan-950/70 to-blue-950/70 border border-cyan-400/40 rounded-xl text-xs text-cyan-200 animate-fadeIn shadow-lg shadow-cyan-950/40">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
                <span>
                  当前帧已选中目标 <strong>[{candidateToLink.class_id || 'Object'}]</strong> (未绑定轨迹)
                </span>
              </div>
              <button
                onClick={handleAddToTrack}
                disabled={isLinking}
                className="px-3.5 py-1 bg-cyan-400 hover:bg-cyan-300 text-gray-950 font-bold rounded-lg transition-all flex items-center gap-1.5 shadow-md shadow-cyan-400/30 active:scale-95 disabled:opacity-50"
              >
                {isLinking ? (
                  <>
                    <span className="w-3 h-3 border-2 border-gray-950 border-t-transparent rounded-full animate-spin" />
                    正在加入...
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                    </svg>
                    将该物体加入此 Track (绑定)
                  </>
                )}
              </button>
            </div>
          ) : !isCurrentFrameTracked ? (
            /* CASE C: MISS frame without selected object -> Helpful guidance */
            <div className="flex items-center justify-between px-3 py-1 bg-gray-900/60 border border-amber-500/20 rounded-xl text-[11px] text-gray-300">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-gray-500" />
                <span>
                  当前帧 (#{currentFrameDisplayNumber}) 尚未关联此轨迹。请在点云或相机画面中框选目标，或点击已有框加入/合并此轨迹。
                </span>
              </div>
              <span className="text-[10px] text-amber-400 font-medium">状态: MISS</span>
            </div>
          ) : null}

          {/* Toast Notice */}
          {toastMessage && (
            <div className="text-center text-xs py-1.5 px-3 text-cyan-200 font-medium bg-cyan-950/80 rounded-lg border border-cyan-400/40 shadow-md animate-fadeIn">
              {toastMessage}
            </div>
          )}
        </div>
      </div>

      {/* ── 1. Detach / Fix Confirmation Modal ── */}
      {showDetachModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm animate-fadeIn">
          <div className="w-[460px] bg-gray-950 border border-rose-500/40 rounded-2xl p-5 shadow-2xl flex flex-col gap-4 text-white">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="font-bold text-base text-rose-300 flex items-center gap-2">
                <svg className="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                轨迹纠偏：修改 / 移出当前帧
              </h3>
              <button
                onClick={() => setShowDetachModal(false)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              您当前位于 <strong className="text-amber-300">帧 #{currentFrameDisplayNumber}</strong>。如果发现该帧目标属于<strong>误跟、目标漂移或错标</strong>，请选择处理方式：
            </p>

            <div className="flex flex-col gap-2.5">
              {/* Option 1: Untrack */}
              <div className="p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl flex items-center justify-between gap-3 transition-colors">
                <div>
                  <div className="font-bold text-sm text-gray-200">从当前轨迹移出 (设为未跟踪)</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">
                    清除 track_id，当前帧立即变灰 (MISS)。目标仍保留在点云中。
                  </div>
                </div>
                <button
                  onClick={() => handleConfirmDetach('untrack')}
                  disabled={isDetaching}
                  className="px-3.5 py-1.5 text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white rounded-lg transition-colors shrink-0"
                >
                  确认移出
                </button>
              </div>

              {/* Option 2: Split to new track */}
              <div className="p-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl flex items-center justify-between gap-3 transition-colors">
                <div>
                  <div className="font-bold text-sm text-amber-300">拆分为全新独立轨迹 (新建 Track)</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">
                    为该目标生成新的 Track ID，自成一条独立轨迹，避免与原车混淆。
                  </div>
                </div>
                <button
                  onClick={() => handleConfirmDetach('split')}
                  disabled={isDetaching}
                  className="px-3.5 py-1.5 text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-gray-950 rounded-lg transition-colors shrink-0"
                >
                  拆分为新Track
                </button>
              </div>
            </div>

            <div className="flex justify-end pt-2 border-t border-white/10">
              <button
                onClick={() => setShowDetachModal(false)}
                className="px-4 py-1.5 text-xs text-gray-400 hover:text-white"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}



      {/* ── 3. Sync Dimensions Confirmation Modal ── */}
      {showSyncModal && baselineDimensions && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm animate-fadeIn">
          <div className="w-[420px] bg-gray-950 border border-cyan-500/40 rounded-2xl p-5 shadow-2xl flex flex-col gap-4 text-white">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="font-bold text-base text-cyan-300 flex items-center gap-2">
                <svg className="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
                  />
                </svg>
                一键统一全轨迹尺寸
              </h3>
              <button
                onClick={() => setShowSyncModal(false)}
                className="text-gray-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              即将以当前基准尺寸，将轨迹 <strong className="text-amber-300">#{shortTrackId}</strong> 线上所有帧（共 <strong className="text-cyan-300">{trackedCount}</strong> 个标注）的边界框长宽高统一同化。
            </p>

            <div className="bg-white/5 border border-white/10 rounded-xl p-3 flex justify-around font-mono text-center">
              <div>
                <span className="text-[10px] text-gray-400 block">长度 (Length)</span>
                <span className="font-bold text-sm text-cyan-300">{baselineDimensions.length.toFixed(3)} m</span>
              </div>
              <div className="border-l border-white/10 pl-4">
                <span className="text-[10px] text-gray-400 block">宽度 (Width)</span>
                <span className="font-bold text-sm text-cyan-300">{baselineDimensions.width.toFixed(3)} m</span>
              </div>
              <div className="border-l border-white/10 pl-4">
                <span className="text-[10px] text-gray-400 block">高度 (Height)</span>
                <span className="font-bold text-sm text-cyan-300">{baselineDimensions.height.toFixed(3)} m</span>
              </div>
            </div>

            <div className="text-[11px] text-amber-300/80 bg-amber-500/10 border border-amber-500/20 rounded-lg p-2 flex items-start gap-1.5">
              <span>💡</span>
              <span>系统将自动保持车辆贴地高度（底面不动），防止车轮陷地或浮空。</span>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-white/10">
              <button
                onClick={() => setShowSyncModal(false)}
                disabled={isSyncing}
                className="px-3.5 py-1.5 text-xs text-gray-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConfirmSync}
                disabled={isSyncing}
                className="px-4 py-1.5 text-xs font-bold bg-cyan-500 hover:bg-cyan-400 text-gray-950 rounded-lg transition-colors flex items-center gap-1.5 shadow-lg shadow-cyan-500/30"
              >
                {isSyncing ? (
                  <>
                    <span className="w-3 h-3 border-2 border-gray-950 border-t-transparent rounded-full animate-spin" />
                    正在同步...
                  </>
                ) : (
                  '确认并广播更新'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
