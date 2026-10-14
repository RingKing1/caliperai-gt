import React from 'react';
import type { Task } from '@/types';

export interface TaskSubmissionModalProps {
  isOpen: boolean;
  isLoadingNextTask: boolean;
  nextTask: Task | null;
  onGoToTaskList: () => void;
  onOpenNextTask: () => void;
}

export const TaskSubmissionModal: React.FC<TaskSubmissionModalProps> = ({
  isOpen,
  isLoadingNextTask,
  nextTask,
  onGoToTaskList,
  onOpenNextTask,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-dark-panel border border-gray-600 rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
        {/* Header */}
        <div className="bg-green-600/20 border-b border-green-600/30 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-green-600 rounded-full flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Task Submitted!</h2>
              <p className="text-sm text-green-300">Your work has been sent for review</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5">
          {isLoadingNextTask ? (
            <div className="flex items-center gap-3 text-gray-400">
              <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              <span>Checking for next task...</span>
            </div>
          ) : nextTask ? (
            <div>
              <p className="text-gray-300 mb-4">
                Would you like to start your next assigned task?
              </p>
              <div className="bg-dark rounded-lg p-3 border border-gray-700">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-medium text-white">{nextTask.name}</h3>
                    <p className="text-sm text-gray-400 mt-1">
                      Frames {nextTask.frame_range.start + 1} - {nextTask.frame_range.end + 1}
                    </p>
                  </div>
                  <span className="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                    {nextTask.status.replace('_', ' ')}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-4">
              <div className="w-12 h-12 bg-gray-700 rounded-full flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-gray-300 font-medium">All caught up!</p>
              <p className="text-sm text-gray-500 mt-1">
                No more tasks are currently assigned to you.
              </p>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="px-6 py-4 bg-dark/50 border-t border-gray-700 flex gap-3">
          {nextTask ? (
            <>
              <button
                onClick={onGoToTaskList}
                className="flex-1 px-4 py-2.5 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 font-medium transition-colors"
              >
                Go to Task List
              </button>
              <button
                onClick={onOpenNextTask}
                className="flex-1 px-4 py-2.5 rounded-lg bg-cyan-600 text-white hover:bg-cyan-500 font-medium transition-colors flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                </svg>
                Open Next Task
              </button>
            </>
          ) : (
            <button
              onClick={onGoToTaskList}
              className="flex-1 px-4 py-2.5 rounded-lg bg-cyan-600 text-white hover:bg-cyan-500 font-medium transition-colors"
            >
              Go to Task List
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
