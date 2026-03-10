import React, { useEffect, useRef, useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { Button } from '@/web/chat/components/ui/button';
import { TaskItem } from './TaskItem';
import type { ConversationSummary } from '../../types';
import { useConversations } from '../../contexts/ConversationsContext';
import { api } from '../../services/api';

interface TaskListProps {
  conversations: ConversationSummary[];
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  activeTab: 'tasks' | 'agents' | 'history' | 'archive';
  onLoadMore: (filters?: {
    hasContinuation?: boolean;
    archived?: boolean;
    pinned?: boolean;
    sessionType?: string;
  }) => void;
}

export function TaskList({
  conversations,
  loading,
  loadingMore,
  hasMore,
  error,
  activeTab,
  onLoadMore
}: TaskListProps) {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef<HTMLDivElement>(null);
  const { recentDirectories, loadConversations } = useConversations();
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);

  // Clear selection when tab changes
  useEffect(() => {
    setSelectedIds(new Set());
  }, [activeTab]);

  // Get filter parameters based on active tab
  const getFiltersForTab = (tab: 'tasks' | 'agents' | 'history' | 'archive') => {
    switch (tab) {
      case 'tasks':
        return { archived: false, hasContinuation: false, sessionType: 'user' };
      case 'agents':
        return { archived: false, hasContinuation: false, sessionType: 'agent' };
      case 'history':
        return { archived: false, hasContinuation: true };
      case 'archive':
        return { archived: true };
      default:
        return {};
    }
  };

  const isSelectable = activeTab === 'agents';

  const handleToggleSelect = (sessionId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectedIds.size === conversations.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(conversations.map(c => c.sessionId)));
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`permanently delete ${selectedIds.size} agent session(s)? This cannot be undone.`)) return;

    setIsBatchDeleting(true);
    try {
      await api.batchDeleteSessions(Array.from(selectedIds));
      setSelectedIds(new Set());
      loadConversations(undefined, getFiltersForTab(activeTab));
    } catch (err) {
      console.error('Failed to batch delete:', err);
    } finally {
      setIsBatchDeleting(false);
    }
  };

  const handleTaskClick = (sessionId: string) => {
    if (renamingSessionId === sessionId) return;
    navigate(`/c/${sessionId}`);
  };

  const handleCancelTask = (sessionId: string) => {
    console.log('Cancel task:', sessionId);
  };

  const handleArchiveTask = async (sessionId: string) => {
    const element = document.querySelector(`[data-session-id="${sessionId}"]`) as HTMLElement;
    if (element) element.style.display = 'none';

    try {
      await api.updateSession(sessionId, { archived: true });
      loadConversations(undefined, getFiltersForTab(activeTab));
    } catch (error) {
      console.error('Failed to archive task:', error);
      if (element) (element as HTMLElement).style.display = '';
    }
  };

  const handleDeleteTask = async (sessionId: string) => {
    const element = document.querySelector(`[data-session-id="${sessionId}"]`) as HTMLElement;
    if (element) element.style.display = 'none';

    try {
      await api.deleteSession(sessionId);
      loadConversations(undefined, getFiltersForTab(activeTab));
    } catch (error) {
      console.error('Failed to delete task:', error);
      if (element) element.style.display = '';
    }
  };

  const handleUnarchiveTask = async (sessionId: string) => {
    const element = document.querySelector(`[data-session-id="${sessionId}"]`) as HTMLElement;
    if (element) element.style.display = 'none';

    try {
      await api.updateSession(sessionId, { archived: false });
      loadConversations(undefined, getFiltersForTab(activeTab));
    } catch (error) {
      console.error('Failed to unarchive task:', error);
      if (element) (element as HTMLElement).style.display = '';
    }
  };

  const handleNameUpdate = async () => {
    setRenamingSessionId(null);
    await loadConversations(undefined, getFiltersForTab(activeTab));
  };

  const handleStartRename = (sessionId: string) => {
    setRenamingSessionId(sessionId);
  };

  const handleCancelRename = () => {
    setRenamingSessionId(null);
  };

  const handlePinToggle = async () => {
    loadConversations(undefined, getFiltersForTab(activeTab));
  };

  // Sort conversations: pinned items first, then by updatedAt
  const sortedConversations = [...conversations].sort((a, b) => {
    if (a.sessionInfo.pinned && !b.sessionInfo.pinned) return -1;
    if (!a.sessionInfo.pinned && b.sessionInfo.pinned) return 1;
    return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
  });

  // Intersection Observer for infinite scrolling
  const handleIntersection = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const [entry] = entries;
      if (entry.isIntersecting && hasMore && !loadingMore && !loading) {
        onLoadMore(getFiltersForTab(activeTab));
      }
    },
    [hasMore, loadingMore, loading, onLoadMore, activeTab]
  );

  useEffect(() => {
    const observer = new IntersectionObserver(handleIntersection, {
      root: scrollRef.current,
      rootMargin: '100px',
      threshold: 0.1,
    });

    const currentLoadingRef = loadingRef.current;
    if (currentLoadingRef) {
      observer.observe(currentLoadingRef);
    }

    return () => {
      if (currentLoadingRef) {
        observer.unobserve(currentLoadingRef);
      }
    };
  }, [handleIntersection]);

  if (loading && conversations.length === 0) {
    return (
      <div className="flex flex-col w-full flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-transparent hover:scrollbar-thumb-border scrollbar-track-transparent">
        <div className="flex items-center justify-center w-full py-12 px-4 text-muted-foreground text-sm text-center bg-background">Loading tasks...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col w-full flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-transparent hover:scrollbar-thumb-border scrollbar-track-transparent">
        <div className="flex items-center justify-center w-full py-12 px-4 text-destructive text-sm text-center bg-background">{error}</div>
      </div>
    );
  }

  const getEmptyMessage = () => {
    switch (activeTab) {
      case 'tasks': return 'No active tasks.';
      case 'agents': return 'No agent sessions.';
      case 'history': return 'No history tasks.';
      case 'archive': return 'No archived tasks.';
      default: return 'No items.';
    }
  };

  if (conversations.length === 0) {
    return (
      <div className="flex flex-col w-full flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-transparent hover:scrollbar-thumb-border scrollbar-track-transparent">
        <div className="flex items-center justify-center w-full py-12 px-4 text-muted-foreground text-sm text-center bg-background">
          {getEmptyMessage()}
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex flex-col w-full flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-transparent hover:scrollbar-thumb-border scrollbar-track-transparent">
      {/* Batch toolbar for Agents tab */}
      {isSelectable && conversations.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-border/30 bg-muted/10">
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={selectedIds.size === conversations.length && conversations.length > 0}
              onChange={handleSelectAll}
              className="rounded border-border"
            />
            Select all
          </label>
          {selectedIds.size > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive hover:bg-destructive/10 h-7 px-2 text-xs"
              onClick={handleBatchDelete}
              disabled={isBatchDeleting}
            >
              <Trash2 size={14} className="mr-1" />
              {isBatchDeleting ? 'Deleting...' : `Delete selected (${selectedIds.size})`}
            </Button>
          )}
        </div>
      )}

      {sortedConversations.map((conversation) => (
        <div key={conversation.sessionId} data-session-id={conversation.sessionId}>
          <TaskItem
            id={conversation.sessionId}
            title={conversation.sessionInfo.custom_name || conversation.summary}
            timestamp={conversation.updatedAt}
            projectPath={conversation.projectPath}
            recentDirectories={recentDirectories}
            status={conversation.status}
            messageCount={conversation.messageCount}
            toolMetrics={conversation.toolMetrics}
            liveStatus={conversation.liveStatus}
            isArchived={activeTab === 'archive'}
            isPinned={conversation.sessionInfo.pinned}
            isSelectable={isSelectable}
            isSelected={selectedIds.has(conversation.sessionId)}
            onToggleSelect={() => handleToggleSelect(conversation.sessionId)}
            onClick={() => handleTaskClick(conversation.sessionId)}
            onCancel={
              conversation.status === 'ongoing'
                ? () => handleCancelTask(conversation.sessionId)
                : undefined
            }
            onArchive={
              conversation.status === 'completed' && activeTab !== 'archive'
                ? () => handleArchiveTask(conversation.sessionId)
                : undefined
            }
            onUnarchive={
              conversation.status === 'completed' && activeTab === 'archive'
                ? () => handleUnarchiveTask(conversation.sessionId)
                : undefined
            }
            onDelete={
              activeTab === 'archive' || activeTab === 'agents'
                ? () => handleDeleteTask(conversation.sessionId)
                : undefined
            }
            isRenaming={renamingSessionId === conversation.sessionId}
            onStartRename={() => handleStartRename(conversation.sessionId)}
            onCancelRename={handleCancelRename}
            onNameUpdate={handleNameUpdate}
            onPinToggle={handlePinToggle}
          />
        </div>
      ))}

      {/* Loading indicator for infinite scroll */}
      {hasMore && (
        <div ref={loadingRef} className="flex items-center justify-center w-full p-4 min-h-[60px]">
          {loadingMore && (
            <div className="flex items-center justify-center text-muted-foreground text-sm animate-pulse">
              Loading more tasks...
            </div>
          )}
        </div>
      )}

      {/* End of list message */}
      {!hasMore && conversations.length > 0 && (
        <div className="flex items-center justify-center w-full p-4 text-muted-foreground/70 text-xs text-center">
          No more tasks to load
        </div>
      )}
    </div>
  );
}
