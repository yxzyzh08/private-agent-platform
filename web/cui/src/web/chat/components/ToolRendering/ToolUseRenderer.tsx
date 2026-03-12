import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { ContentBlockParam } from '@anthropic-ai/sdk/resources/messages/messages';
import type { ChatMessage, ToolResult } from '../../types';
import { ToolLabel } from './ToolLabel';
import { ToolContent } from './ToolContent';

interface ToolUse {
  type: 'tool_use';
  id: string;
  name: string;
  input: any;
}

interface ToolUseRendererProps {
  toolUse: ToolUse;
  toolResult?: ToolResult;
  toolResults?: Record<string, ToolResult>;
  workingDirectory?: string;
  childrenMessages?: Record<string, ChatMessage[]>;
  expandedTasks?: Set<string>;
  onToggleTaskExpanded?: (toolUseId: string) => void;
  /** If true, start expanded (used for grouped items when group is expanded) */
  defaultExpanded?: boolean;
}

export function ToolUseRenderer({
  toolUse,
  toolResult,
  toolResults = {},
  workingDirectory,
  childrenMessages = {},
  expandedTasks = new Set(),
  onToggleTaskExpanded,
  defaultExpanded = false
}: ToolUseRendererProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const isPending = !toolResult || toolResult.status === 'pending';

  return (
    <div className="flex flex-col">
      {/* Summary line: clickable label with expand chevron */}
      <div
        className="flex items-center gap-1 cursor-pointer select-none group"
        onClick={() => !isPending && setIsExpanded(!isExpanded)}
      >
        {!isPending && (
          <ChevronRight
            size={12}
            className={`text-muted-foreground transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
          />
        )}
        <ToolLabel
          toolName={toolUse.name}
          toolInput={toolUse.input}
          workingDirectory={workingDirectory}
        />
      </div>

      {/* Detail content: only shown when expanded */}
      {isExpanded && !isPending && (
        <div className="mt-1 ml-4">
          <ToolContent
            toolName={toolUse.name}
            toolInput={toolUse.input}
            toolResult={toolResult}
            workingDirectory={workingDirectory}
            toolUseId={toolUse.id}
            childrenMessages={childrenMessages}
            toolResults={toolResults}
          />
        </div>
      )}
    </div>
  );
}
