import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useEditorStore } from '@/store/editorStore';

export type ToolType = 'select' | 'cuboid' | 'box2d' | 'polygon' | 'polyline' | 'brush3d' | 'track' | 'flag_missing';
export type AnnotationCapability = 'bounding_box_3d' | 'bounding_box_2d' | 'semantic_segmentation' | 'instance_segmentation' | 'tracking' | 'polygon' | 'polyline';

export interface Tool {
  id: ToolType;
  name: string;
  icon: JSX.Element;
  shortcut: string;
  capability?: AnnotationCapability;
}

export const allTools: Tool[] = [
  {
    id: 'cuboid',
    name: '3D Box',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    ),
    shortcut: 'C',
    capability: 'bounding_box_3d',
  },
  {
    id: 'track',
    name: 'Track',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    ),
    shortcut: 'T',
    capability: 'tracking',
  },
];

export const qaTools: Tool[] = [
  {
    id: 'flag_missing',
    name: 'Flag Missing',
    icon: (
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
      </svg>
    ),
    shortcut: 'F',
  },
];

export const ClassPickerPanel: React.FC = () => {
  const { activeTool, taxonomy, activeClassId, setActiveClass, isBoxPlacementActive, pendingClassDigits } =
    useEditorStore();

  const showClassPicker = (activeTool === 'cuboid' || activeTool === 'track') && !isBoxPlacementActive;
  const activeClass = taxonomy?.classes?.find((c) => c.id === activeClassId);

  const classPickerScrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!activeClassId || !classPickerScrollRef.current) return;
    const el = classPickerScrollRef.current.querySelector(`[data-classpicker-id="${activeClassId}"]`);
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activeClassId, showClassPicker]);

  if (!showClassPicker || !taxonomy?.classes?.length) return null;

  return (
    <div className="w-52 bg-dark-panel/95 backdrop-blur-sm rounded-xl border border-gray-700 shadow-xl overflow-hidden">
      <div className="px-3 py-1.5 border-b border-gray-700 flex items-center justify-between">
        <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
          {activeTool === 'track' ? 'Track Class' : 'Box Class'}
        </span>
        {pendingClassDigits ? (
          <span className="text-[10px] font-mono bg-primary/30 text-primary px-1.5 py-0.5 rounded border border-primary/50 animate-pulse">
            #{pendingClassDigits}…
          </span>
        ) : (
          <span className="text-[10px] text-gray-600 font-mono">1-9, 0, 10+</span>
        )}
      </div>
      <div className="max-h-52 overflow-y-auto" ref={classPickerScrollRef}>
        {taxonomy.classes.map((cls, idx) => (
          <button
            key={cls.id}
            data-classpicker-id={cls.id}
            onClick={() => setActiveClass(cls.id)}
            className={`w-full flex items-center gap-2 px-3 py-1.5 text-left transition-all ${
              activeClassId === cls.id
                ? 'bg-primary/20 text-white'
                : 'text-gray-400 hover:bg-dark-hover hover:text-white'
            }`}
          >
            <span
              className="w-2.5 h-2.5 rounded flex-shrink-0"
              style={{ backgroundColor: cls.color }}
            />
            <span className="text-xs truncate flex-1">{cls.name}</span>
            {activeClassId === cls.id && (
              <span className="text-[10px] text-primary font-bold">✓</span>
            )}
            <span className="text-[10px] text-gray-600 font-mono">
              {idx < 9 ? idx + 1 : idx === 9 ? '0' : ''}
            </span>
          </button>
        ))}
      </div>
      {activeClass && (
        <div className="px-3 py-1 bg-dark/60 border-t border-gray-700/60 flex items-center gap-1.5">
          <span className="w-2 h-2 rounded" style={{ backgroundColor: activeClass.color }} />
          <span className="text-[10px] text-gray-400">Click on scene to place</span>
        </div>
      )}
    </div>
  );
};

export interface ToolPaletteProps {
  availableCapabilities: AnnotationCapability[];
  isQAMode?: boolean;
}

export const ToolPalette: React.FC<ToolPaletteProps> = ({ availableCapabilities, isQAMode = false }) => {
  const { activeTool, setActiveTool } = useEditorStore();
  const taskId = useEditorStore((s) => s.task?.id);

  // Timer nudge toast — shown when user picks an annotation tool without the timer running
  const [showTimerToast, setShowTimerToast] = useState(false);
  const timerToastTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [timerRunning, setTimerRunning] = useState<boolean>(false);

  useEffect(() => {
    if (!taskId) return;
    try {
      const raw = localStorage.getItem(`task_timer_${taskId}`);
      if (raw !== null) {
        setTimerRunning(JSON.parse(raw).running === true);
      }
    } catch {
      /* ignore */
    }
  }, [taskId]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ running: boolean; taskId: string }>).detail;
      if (detail?.taskId === taskId) {
        setTimerRunning(detail.running);
        if (detail.running) {
          setShowTimerToast(false);
          if (timerToastTimeoutRef.current) clearTimeout(timerToastTimeoutRef.current);
        }
      }
    };
    window.addEventListener('timerStateChange', handler);
    return () => window.removeEventListener('timerStateChange', handler);
  }, [taskId]);

  // Filter available tools based on capabilities
  const availableTools = allTools.filter((tool) => {
    if (!tool.capability) return true;
    return availableCapabilities.includes(tool.capability);
  });

  const toolsToShow = isQAMode ? qaTools : availableTools;

  return (
    <>
      {/* Timer nudge toast */}
      {showTimerToast &&
        createPortal(
          <div className="fixed top-14 left-1/2 -translate-x-1/2 z-[300] pointer-events-none flex justify-center">
            <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-gray-900 border border-amber-500/45 animate-fadeInDown animate-timerToastGlow pointer-events-auto">
              <span className="flex-shrink-0 w-7 h-7 rounded-full bg-amber-500/15 border border-amber-500/30 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <circle cx="12" cy="12" r="9" />
                  <path strokeLinecap="round" d="M12 7v5l3 3" />
                </svg>
              </span>
              <div className="flex flex-col">
                <span className="text-xs font-semibold text-amber-300 leading-tight">Start the timer</span>
                <span className="text-[11px] text-gray-400 leading-tight mt-0.5">
                  Press play on the timer (top-right) to log your work time
                </span>
              </div>
              <button
                className="ml-1 flex-shrink-0 text-gray-500 hover:text-gray-300 transition-colors"
                onClick={() => {
                  setShowTimerToast(false);
                  if (timerToastTimeoutRef.current) clearTimeout(timerToastTimeoutRef.current);
                }}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>,
          document.body
        )}
      <div data-tour="tool-palette-3d" className="absolute left-4 top-1/2 -translate-y-1/2 z-20 flex items-start gap-2">
        <div className="bg-dark-panel/95 backdrop-blur-sm rounded-xl border border-gray-700 p-2 shadow-xl">
          <div className="flex flex-col gap-1">
            {toolsToShow.map((tool, index) => {
              const isAnnotationTool = tool.id !== 'flag_missing';
              const timerLocked = isAnnotationTool && !timerRunning;
              return (
                <React.Fragment key={tool.id}>
                  {/* Add separator before QA tools */}
                  {isQAMode &&
                    index ===
                      availableTools.filter((t) => !t.capability || availableCapabilities.includes(t.capability)).length && (
                      <div className="border-t border-orange-500/50 my-1" />
                    )}
                  <button
                    data-tour={`${tool.id}-tool`}
                    onMouseEnter={() => {
                      if (timerLocked)
                        window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: true } }));
                    }}
                    onMouseLeave={() => {
                      if (timerLocked)
                        window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: false } }));
                    }}
                    onFocus={() => {
                      if (timerLocked)
                        window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: true } }));
                    }}
                    onBlur={() => {
                      if (timerLocked)
                        window.dispatchEvent(new CustomEvent('timerControlAttention', { detail: { active: false } }));
                    }}
                    onClick={() => {
                      if (timerLocked) {
                        if (timerToastTimeoutRef.current) clearTimeout(timerToastTimeoutRef.current);
                        setShowTimerToast(true);
                        timerToastTimeoutRef.current = setTimeout(() => setShowTimerToast(false), 8000);
                        return;
                      }
                      setActiveTool(tool.id);
                    }}
                    className={`group relative p-3 rounded-lg transition-all ${
                      timerLocked
                        ? 'text-amber-700/40 cursor-not-allowed'
                        : activeTool === tool.id
                        ? tool.id === 'flag_missing'
                          ? 'bg-orange-500 text-white shadow-lg shadow-orange-500/30'
                          : 'bg-primary text-white shadow-lg shadow-primary/30'
                        : tool.id === 'flag_missing'
                        ? 'text-orange-400 hover:bg-orange-500/20 hover:text-orange-300'
                        : 'text-gray-400 hover:bg-dark-hover hover:text-white'
                    }`}
                    aria-label={`${tool.name} (${tool.shortcut})`}
                  >
                    {tool.icon}
                    {timerLocked ? (
                      <span className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-3 whitespace-nowrap px-3 py-2 rounded-lg bg-white border border-amber-400 text-sm font-medium text-amber-700 shadow-xl z-50 invisible scale-95 group-hover:visible group-hover:scale-100 group-focus-visible:visible group-focus-visible:scale-100 transition-transform duration-150">
                        {tool.name} — start the timer first
                      </span>
                    ) : (
                      <span className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-3 whitespace-nowrap px-3 py-2 rounded-lg bg-white border border-gray-200 text-sm text-gray-800 shadow-xl z-50 invisible scale-95 group-hover:visible group-hover:scale-100 group-focus-visible:visible group-focus-visible:scale-100 transition-transform duration-150">
                        {tool.name} ({tool.shortcut})
                      </span>
                    )}
                    {/* Lock badge overlay for timer-locked tools */}
                    {timerLocked && (
                      <span className="absolute bottom-0.5 right-0.5 w-3 h-3 flex items-center justify-center">
                        <svg className="w-2.5 h-2.5 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
                          <path
                            fillRule="evenodd"
                            d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </span>
                    )}
                  </button>
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
};
