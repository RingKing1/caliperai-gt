import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useEditorStore } from '@/store/editorStore';
import { useLidarCacheStore } from '@/store/lidarCacheStore';
import { useImageCacheStore } from '@/store/imageCacheStore';

type PlaybackSpeed = 0.25 | 0.5 | 1 | 2 | 4;
const PLAYBACK_SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2, 4];
const BASE_INTERVAL = 200; // ms at 1x speed

export interface TimelineProps {
  isLoadingFrame?: boolean;
  displayedFrameIndex?: number;
}

export const Timeline: React.FC<TimelineProps> = ({ isLoadingFrame = false, displayedFrameIndex }) => {
  const {
    frames,
    scene,
    task,
    currentFrameIndex,
    goToFrame,
    nextFrame,
    prevFrame,
    keyframeSamplingEnabled,
    keyframeInterval,
    keyframeStartFrame,
    setKeyframeSamplingEnabled,
    setKeyframeInterval,
    setKeyframeStartFrame,
    isKeyframeAt,
  } = useEditorStore();
  const lidarPrefetchStatus = useLidarCacheStore((s) => s.prefetchStatus);
  const lidarPrefetchProgress = useLidarCacheStore((s) => s.prefetchProgress);
  const lidarPrefetchTotal = useLidarCacheStore((s) => s.prefetchTotal);
  const imagePrefetchStatus = useImageCacheStore((s) => s.prefetchStatus);
  const imagePrefetchProgress = useImageCacheStore((s) => s.prefetchProgress);
  const imagePrefetchTotal = useImageCacheStore((s) => s.prefetchTotal);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<PlaybackSpeed>(1);
  const [isEditingFrame, setIsEditingFrame] = useState(false);
  const [frameInputValue, setFrameInputValue] = useState('');
  const playIntervalRef = useRef<number | null>(null);
  const frameInputRef = useRef<HTMLInputElement>(null);

  // Keyframe sampling menu state
  const [showKeyframeMenu, setShowKeyframeMenu] = useState(false);
  const keyframeMenuRef = useRef<HTMLDivElement>(null);

  // Drag-to-move state
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const initialOffset = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (keyframeMenuRef.current && !keyframeMenuRef.current.contains(e.target as Node)) {
        setShowKeyframeMenu(false);
      }
    };
    if (showKeyframeMenu) {
      window.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      window.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showKeyframeMenu]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      setOffset({
        x: initialOffset.current.x + (e.clientX - dragStart.current.x),
        y: initialOffset.current.y + (e.clientY - dragStart.current.y),
      });
    };
    const handleMouseUp = () => setIsDragging(false);
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging]);

  const handlePillMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button') || (e.target as HTMLElement).closest('input')) return;
    setIsDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
    initialOffset.current = { ...offset };
  };

  // Use displayed frame index if provided, otherwise fall back to current
  const shownFrameIndex = displayedFrameIndex ?? currentFrameIndex;

  const keyframeIndices = useMemo(() => {
    if (!keyframeSamplingEnabled || frames.length === 0) return [];
    const interval = Math.max(1, keyframeInterval);
    const indices: number[] = [];
    for (let i = keyframeStartFrame; i < frames.length; i += interval) {
      indices.push(i);
    }
    return indices;
  }, [keyframeSamplingEnabled, keyframeInterval, keyframeStartFrame, frames.length]);

  const currentIsKeyframe = keyframeSamplingEnabled && isKeyframeAt(shownFrameIndex);

  useEffect(() => {
    if (isPlaying) {
      const interval = BASE_INTERVAL / playbackSpeed;
      playIntervalRef.current = window.setInterval(() => {
        if (isLoadingFrame) return;
        const store = useEditorStore.getState();
        if (store.currentFrameIndex < store.frames.length - 1) {
          store.nextFrame();
        } else {
          setIsPlaying(false);
        }
      }, interval);
    } else {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    }
    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [isPlaying, isLoadingFrame, playbackSpeed]);

  const goToFirstFrame = useCallback(() => {
    goToFrame(0);
    setIsPlaying(false);
  }, [goToFrame]);

  const goToLastFrame = useCallback(() => {
    goToFrame(frames.length - 1);
    setIsPlaying(false);
  }, [goToFrame, frames.length]);

  const handleFrameInputStart = () => {
    setIsEditingFrame(true);
    setFrameInputValue(String(shownFrameIndex + 1));
    setTimeout(() => frameInputRef.current?.select(), 0);
  };

  const handleFrameInputSubmit = () => {
    const frameNum = parseInt(frameInputValue);
    if (!isNaN(frameNum) && frameNum >= 1 && frameNum <= frames.length) {
      goToFrame(frameNum - 1);
    }
    setIsEditingFrame(false);
  };

  const handleFrameInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleFrameInputSubmit();
    else if (e.key === 'Escape') setIsEditingFrame(false);
  };

  const cyclePlaybackSpeed = (e: React.MouseEvent) => {
    e.stopPropagation();
    const currentIndex = PLAYBACK_SPEEDS.indexOf(playbackSpeed);
    const nextIndex = (currentIndex + 1) % PLAYBACK_SPEEDS.length;
    setPlaybackSpeed(PLAYBACK_SPEEDS[nextIndex]);
  };

  const progress = frames.length > 1 ? (shownFrameIndex / (frames.length - 1)) * 100 : 0;

  const isPrefetching = lidarPrefetchStatus === 'prefetching' || imagePrefetchStatus === 'prefetching';
  const isPrefetchComplete = lidarPrefetchStatus === 'complete' && imagePrefetchStatus === 'complete' && lidarPrefetchTotal > 0 && imagePrefetchTotal > 0;

  const iconBtn = (disabled = false) =>
    `p-1 rounded-full hover:bg-white/10 text-white/50 hover:text-white transition-colors ${disabled ? 'opacity-25 pointer-events-none' : ''}`;

  return (
    <div
      data-tour="timeline"
      className="absolute bottom-5 left-1/2 z-40"
      style={{ transform: `translate(calc(-50% + ${offset.x}px), ${offset.y}px)` }}
    >
      <div
        className={`flex items-center gap-1 px-2.5 py-1.5 bg-gray-950/85 backdrop-blur-xl border border-white/8 rounded-full shadow-2xl shadow-black/50 select-none ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
        onMouseDown={handlePillMouseDown}
      >

        {/* ── First Frame ── */}
        <button
          onClick={goToFirstFrame}
          disabled={currentFrameIndex === 0}
          className={iconBtn(currentFrameIndex === 0)}
          title="First Frame (Home)"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
            <path d="M6 6h2v12H6V6zm3.5 6 8.5 6V6l-8.5 6z"/>
          </svg>
        </button>

        {/* ── Prev Frame ── */}
        <button
          onClick={prevFrame}
          disabled={currentFrameIndex === 0}
          className={iconBtn(currentFrameIndex === 0)}
          title="Previous (←)"
        >
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z"/>
          </svg>
        </button>

        {/* ── Play / Pause ── */}
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          className={`w-7 h-7 flex items-center justify-center rounded-full transition-colors duration-150 ${
            isPlaying
              ? 'bg-white text-gray-900 shadow-md shadow-white/20'
              : 'bg-white/12 text-white hover:bg-white/20'
          }`}
          title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
        >
          {isPlaying ? (
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
            </svg>
          ) : (
            <svg className="w-3 h-3 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z"/>
            </svg>
          )}
        </button>

        {/* ── Next Frame ── */}
        <button
          onClick={nextFrame}
          disabled={currentFrameIndex >= frames.length - 1}
          className={iconBtn(currentFrameIndex >= frames.length - 1)}
          title="Next (→)"
        >
          <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>
          </svg>
        </button>

        {/* ── Last Frame ── */}
        <button
          onClick={goToLastFrame}
          disabled={currentFrameIndex >= frames.length - 1}
          className={iconBtn(currentFrameIndex >= frames.length - 1)}
          title="Last Frame (End)"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
            <path d="M8 5v14l11-7L8 5zM18 5v14h2V5h-2z"/>
          </svg>
        </button>

        {/* ── Divider ── */}
        <div className="mx-1 w-px h-4 bg-white/10" />

        {/* ── Progress Scrubber ── */}
        <div className="relative group flex items-center">
          <div className="relative w-36 h-1.5 bg-white/10 rounded-full overflow-visible cursor-pointer">
            <div
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-400 to-cyan-400 rounded-full pointer-events-none"
              style={{ width: `${progress}%` }}
            />
            {/* Keyframe tick marks */}
            {keyframeSamplingEnabled && keyframeIndices.map((idx) => {
              const leftPercent = frames.length > 1 ? (idx / (frames.length - 1)) * 100 : 0;
              const isCurrent = idx === shownFrameIndex;
              return (
                <div
                  key={`kf-tick-${idx}`}
                  className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 rounded-full pointer-events-none z-10 transition-transform ${
                    isCurrent
                      ? 'w-2 h-2 bg-amber-300 ring-2 ring-amber-400/50 scale-125'
                      : 'w-1 h-1 bg-amber-400/80'
                  }`}
                  style={{ left: `${leftPercent}%` }}
                />
              );
            })}
            <div
              className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 bg-white rounded-full shadow pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ left: `calc(${progress}% - 5px)` }}
            />
            <input
              type="range"
              min={0}
              max={Math.max(0, frames.length - 1)}
              value={currentFrameIndex}
              onChange={(e) => goToFrame(parseInt(e.target.value))}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
          </div>
        </div>

        {/* ── Divider ── */}
        <div className="mx-1 w-px h-4 bg-white/10" />

        {/* ── Frame Counter & Keyframe Badge ── */}
        <div className="flex items-center gap-1">
          {isEditingFrame ? (
            <input
              ref={frameInputRef}
              type="text"
              value={frameInputValue}
              onChange={(e) => setFrameInputValue(e.target.value.replace(/\D/g, ''))}
              onBlur={handleFrameInputSubmit}
              onKeyDown={handleFrameInputKeyDown}
              className="w-12 px-1 py-0.5 text-[10px] font-mono bg-white/10 border border-blue-400/50 rounded text-white text-center focus:outline-none"
              autoFocus
            />
          ) : (
            <button
              onClick={handleFrameInputStart}
              className="flex items-center gap-px text-[10px] font-mono hover:text-white transition-colors whitespace-nowrap"
              title="Click to jump to frame"
            >
              <span className="font-semibold text-white/90">{(frames[shownFrameIndex]?.frame_index ?? shownFrameIndex) + 1}</span>
              <span className="text-white/35">/{task?.frame_range ? task.frame_range.end + 1 : (scene?.frame_count ?? frames.length)}</span>
              {isLoadingFrame && (
                <span className="ml-0.5 w-1.5 h-1.5 bg-amber-400 rounded-full animate-pulse" />
              )}
            </button>
          )}

          {keyframeSamplingEnabled && (
            <span
              className={`px-1 py-0.2 text-[8.5px] font-mono rounded font-semibold tracking-wider transition-colors ${
                currentIsKeyframe
                  ? 'bg-amber-400/25 text-amber-300 border border-amber-400/40 shadow-sm shadow-amber-500/20'
                  : 'bg-white/5 text-gray-500'
              }`}
              title={currentIsKeyframe ? "当前帧是关键帧 (在此打标)" : "当前帧为插值帧"}
            >
              {currentIsKeyframe ? 'KF' : 'INTERP'}
            </span>
          )}
        </div>

        {/* ── Divider ── */}
        <div className="mx-1 w-px h-4 bg-white/10" />

        {/* ── Speed Control ── */}
        <button
          onClick={cyclePlaybackSpeed}
          className={`px-1.5 py-0.5 text-[10px] font-semibold rounded transition-colors ${
            playbackSpeed !== 1
              ? 'bg-blue-500/20 text-blue-300 border border-blue-400/30'
              : 'text-white/45 hover:text-white hover:bg-white/10'
          }`}
          title="Click to cycle speed"
        >
          {playbackSpeed}×
        </button>

        {/* ── Divider ── */}
        <div className="mx-1 w-px h-4 bg-white/10" />

        {/* ── Keyframe Sampling Button & Dropdown ── */}
        <div className="relative" ref={keyframeMenuRef}>
          <button
            onClick={(e) => {
              e.stopPropagation();
              setShowKeyframeMenu(!showKeyframeMenu);
            }}
            className={`px-2 py-0.5 text-[10px] font-semibold rounded-full flex items-center gap-1 transition-all ${
              keyframeSamplingEnabled
                ? 'bg-amber-500/25 text-amber-300 border border-amber-400/50 shadow-sm shadow-amber-500/20'
                : 'text-white/45 hover:text-white hover:bg-white/10'
            }`}
            title="关键帧抽样标注设置 (Keyframe Sampling)"
          >
            <span className={`w-1.5 h-1.5 rounded-full ${keyframeSamplingEnabled ? 'bg-amber-400 animate-pulse' : 'bg-gray-500'}`} />
            <span>关键帧</span>
            {keyframeSamplingEnabled && (
              <span className="font-mono text-[9px] text-amber-200">
                每{keyframeInterval}帧
              </span>
            )}
          </button>

          {showKeyframeMenu && (
            <div
              className="absolute bottom-full mb-3 right-0 w-64 bg-gray-950/95 border border-amber-500/30 rounded-xl shadow-2xl p-3 backdrop-blur-2xl text-xs text-white z-50 flex flex-col gap-2.5"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between pb-1.5 border-b border-white/10">
                <span className="font-semibold text-amber-400 flex items-center gap-1.5">
                  <span className="w-2 h-2 rotate-45 bg-amber-400 inline-block" />
                  只标注关键帧
                </span>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={keyframeSamplingEnabled}
                    onChange={(e) => setKeyframeSamplingEnabled(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-7 h-4 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-amber-500"></div>
                </label>
              </div>

              {/* 起始帧选择 */}
              <div className="flex items-center justify-between">
                <span className="text-gray-300 text-[11px]">关键帧起始:</span>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={1}
                    max={frames.length || 1}
                    value={keyframeStartFrame + 1}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (!isNaN(val)) {
                        setKeyframeStartFrame(Math.max(0, Math.min(frames.length - 1, val - 1)));
                      }
                    }}
                    className="w-14 px-1.5 py-0.5 text-center font-mono bg-white/10 border border-white/15 rounded text-white focus:outline-none focus:border-amber-400 text-xs"
                  />
                  <button
                    onClick={() => setKeyframeStartFrame(shownFrameIndex)}
                    className="px-1.5 py-0.5 text-[10px] bg-white/10 hover:bg-white/20 text-gray-200 rounded transition-colors whitespace-nowrap"
                    title="将当前帧设为关键帧起点"
                  >
                    设为当前
                  </button>
                </div>
              </div>

              {/* 关键帧间隔 */}
              <div className="flex items-center justify-between">
                <span className="text-gray-300 text-[11px]">关键帧间隔:</span>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={keyframeInterval}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10);
                      if (!isNaN(val) && val >= 1) {
                        setKeyframeInterval(val);
                      }
                    }}
                    className="w-14 px-1.5 py-0.5 text-center font-mono bg-white/10 border border-white/15 rounded text-white focus:outline-none focus:border-amber-400 text-xs"
                  />
                  <span className="text-gray-400 text-[10px]">帧</span>
                </div>
              </div>

              {/* 快捷间隔预设 */}
              <div className="flex items-center gap-1 pt-0.5">
                <span className="text-[10px] text-gray-400 mr-1">预设:</span>
                {[5, 10, 15, 20].map((step) => (
                  <button
                    key={step}
                    onClick={() => setKeyframeInterval(step)}
                    className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                      keyframeInterval === step
                        ? 'bg-amber-500/30 text-amber-300 border border-amber-400/40'
                        : 'bg-white/5 hover:bg-white/10 text-gray-300'
                    }`}
                  >
                    {step}帧
                  </button>
                ))}
              </div>

              {/* 统计提示与状态 */}
              <div className="pt-1.5 border-t border-white/10 text-[10px] text-gray-400 flex items-center justify-between">
                <span>序列共 {keyframeIndices.length} 个关键帧</span>
                {keyframeSamplingEnabled && (
                  <span className={currentIsKeyframe ? "text-amber-400 font-semibold" : "text-gray-400"}>
                    {currentIsKeyframe ? "★ 当前为关键帧" : "当前为插值帧"}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Prefetch Status ── */}
        {isPrefetching && (
          <>
            <div className="mx-1 w-px h-4 bg-white/10" />
            <div className="w-8 h-1 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-cyan-400/60 transition-all duration-300"
                style={{ width: `${Math.max(lidarPrefetchProgress, imagePrefetchProgress)}%` }}
              />
            </div>
          </>
        )}
        {isPrefetchComplete && (
          <span title="All frames ready" className="ml-1">
            <svg className="w-3 h-3 text-green-400/70" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          </span>
        )}

      </div>
    </div>
  );
};
