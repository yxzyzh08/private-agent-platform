import React, { useEffect, useRef, useState, useCallback } from 'react';
import { TaskCard, type TaskState } from './TaskCard';

interface RequirementPanelProps {
  planId: string | null;
  proxyBaseUrl?: string;
  onClose?: () => void;
}

type PlanStatus = 'connecting' | 'executing' | 'completed' | 'failed' | 'stopped';

export function RequirementPanel({
  planId,
  proxyBaseUrl = '/api/proxy',
  onClose,
}: RequirementPanelProps) {
  const [tasks, setTasks] = useState<TaskState[]>([]);
  const [totalTasks, setTotalTasks] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [planStatus, setPlanStatus] = useState<PlanStatus>('connecting');
  const [totalDuration, setTotalDuration] = useState<number | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // SSE connection
  useEffect(() => {
    if (!planId) return;

    setPlanStatus('connecting');
    setTasks([]);
    setCompletedCount(0);
    setTotalDuration(null);

    const url = `${proxyBaseUrl}/requirements/${planId}/events`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener('plan_started', (e) => {
      const data = JSON.parse(e.data);
      setTotalTasks(data.total_tasks || 0);
      setPlanStatus('executing');
    });

    es.addEventListener('task_started', (e) => {
      const data = JSON.parse(e.data);
      setTasks((prev) => {
        const existing = prev.find((t) => t.task_id === data.task_id);
        if (existing) {
          return prev.map((t) =>
            t.task_id === data.task_id
              ? { ...t, status: 'in_progress' as const, title: data.title || t.title }
              : t
          );
        }
        return [
          ...prev,
          {
            task_id: data.task_id,
            title: data.title || data.task_id,
            status: 'in_progress' as const,
          },
        ];
      });
    });

    es.addEventListener('task_completed', (e) => {
      const data = JSON.parse(e.data);
      setTasks((prev) =>
        prev.map((t) =>
          t.task_id === data.task_id
            ? { ...t, status: 'completed' as const, duration_ms: data.duration_ms }
            : t
        )
      );
      setCompletedCount((c) => c + 1);
    });

    es.addEventListener('task_failed', (e) => {
      const data = JSON.parse(e.data);
      setTasks((prev) =>
        prev.map((t) =>
          t.task_id === data.task_id
            ? {
                ...t,
                status: 'failed' as const,
                error: data.error,
                attempt: data.attempt,
              }
            : t
        )
      );
    });

    es.addEventListener('plan_completed', (e) => {
      const data = JSON.parse(e.data);
      setPlanStatus('completed');
      setTotalDuration(data.total_duration_ms || null);
      es.close();
    });

    es.addEventListener('plan_failed', (e) => {
      setPlanStatus('failed');
      es.close();
    });

    es.addEventListener('plan_stopped', (e) => {
      setPlanStatus('stopped');
      es.close();
    });

    es.addEventListener('heartbeat', () => {
      // Keep-alive, no action needed
    });

    es.onerror = () => {
      // EventSource auto-reconnects on error
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [planId, proxyBaseUrl]);

  // Control actions
  const handleRetry = useCallback(
    async (taskId: string) => {
      if (!planId) return;
      await fetch(
        `${proxyBaseUrl}/requirements/${planId}/tasks/${taskId}/retry`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
      );
    },
    [planId, proxyBaseUrl]
  );

  const handleSkip = useCallback(
    async (taskId: string) => {
      if (!planId) return;
      await fetch(
        `${proxyBaseUrl}/requirements/${planId}/tasks/${taskId}/skip`,
        { method: 'POST' }
      );
    },
    [planId, proxyBaseUrl]
  );

  const handleAbort = useCallback(async () => {
    if (!planId) return;
    await fetch(`${proxyBaseUrl}/requirements/${planId}/abort`, {
      method: 'POST',
    });
  }, [planId, proxyBaseUrl]);

  // Don't render if no planId
  if (!planId) return null;

  const progress =
    totalTasks > 0 ? Math.round((completedCount / totalTasks) * 100) : 0;

  return (
    <div className="w-80 border-l border-border bg-background flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold">Execution Progress</h3>
        {onClose && (
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            &times;
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex justify-between text-xs text-muted-foreground mb-1">
          <span>
            {completedCount}/{totalTasks} tasks
          </span>
          <span>{progress}%</span>
        </div>
        <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        {planStatus === 'completed' && totalDuration != null && (
          <div className="text-xs text-muted-foreground mt-1">
            Total: {Math.round(totalDuration / 1000)}s
          </div>
        )}
      </div>

      {/* Status banner */}
      {planStatus === 'completed' && (
        <div className="px-4 py-2 bg-green-500/10 text-green-600 text-xs font-medium">
          All tasks completed successfully
        </div>
      )}
      {planStatus === 'failed' && (
        <div className="px-4 py-2 bg-red-500/10 text-red-600 text-xs font-medium">
          Plan failed — use retry or skip on failed tasks
        </div>
      )}
      {planStatus === 'stopped' && (
        <div className="px-4 py-2 bg-yellow-500/10 text-yellow-600 text-xs font-medium">
          Plan stopped by owner
        </div>
      )}

      {/* Task list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {tasks.map((task) => (
          <TaskCard
            key={task.task_id}
            task={task}
            onRetry={handleRetry}
            onSkip={handleSkip}
          />
        ))}
        {tasks.length === 0 && planStatus === 'connecting' && (
          <div className="text-center text-muted-foreground text-sm py-8">
            Connecting...
          </div>
        )}
      </div>

      {/* Footer actions */}
      {planStatus === 'executing' && (
        <div className="px-4 py-3 border-t border-border">
          <button
            onClick={handleAbort}
            className="w-full text-xs px-3 py-1.5 rounded bg-destructive/10 hover:bg-destructive/20 text-destructive font-medium"
          >
            Abort Plan
          </button>
        </div>
      )}
    </div>
  );
}
