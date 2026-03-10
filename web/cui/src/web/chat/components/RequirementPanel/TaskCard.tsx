import React from 'react';

export interface TaskState {
  task_id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
  duration_ms?: number;
  error?: string;
  attempt?: number;
}

interface TaskCardProps {
  task: TaskState;
  onRetry?: (taskId: string) => void;
  onSkip?: (taskId: string) => void;
}

const STATUS_ICONS: Record<string, string> = {
  pending: '\u23f3',
  in_progress: '\ud83d\udd04',
  completed: '\u2705',
  failed: '\u274c',
  skipped: '\u23ed\ufe0f',
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

export function TaskCard({ task, onRetry, onSkip }: TaskCardProps) {
  const icon = STATUS_ICONS[task.status] || '\u2753';

  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-md bg-secondary/50 text-sm">
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <span className="flex-shrink-0">{icon}</span>
        <span className="truncate font-medium">
          {task.task_id}: {task.title}
        </span>
        {task.duration_ms != null && task.status === 'completed' && (
          <span className="text-muted-foreground text-xs flex-shrink-0">
            ({formatDuration(task.duration_ms)})
          </span>
        )}
      </div>
      {task.status === 'failed' && (
        <div className="flex gap-1 ml-2 flex-shrink-0">
          {onRetry && (
            <button
              onClick={() => onRetry(task.task_id)}
              className="text-xs px-2 py-0.5 rounded bg-primary/10 hover:bg-primary/20 text-primary"
            >
              Retry
            </button>
          )}
          {onSkip && (
            <button
              onClick={() => onSkip(task.task_id)}
              className="text-xs px-2 py-0.5 rounded bg-muted hover:bg-muted/80 text-muted-foreground"
            >
              Skip
            </button>
          )}
        </div>
      )}
    </div>
  );
}
