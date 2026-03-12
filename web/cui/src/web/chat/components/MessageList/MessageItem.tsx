import React, { useState } from 'react';
import { Copy, Check, Code, Globe, Settings, FileText, Edit, Terminal, Search, List, CheckSquare, ExternalLink, Play, FileEdit, ClipboardList, Maximize2, Minimize2, ChevronRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { JsonViewer } from '../JsonViewer/JsonViewer';
import { ToolUseRenderer } from '../ToolRendering/ToolUseRenderer';
import { markdownComponents } from '../shared/markdownComponents';
import type { ChatMessage, ToolResult } from '../../types';
import type { ContentBlockParam } from '@anthropic-ai/sdk/resources/messages/messages';

interface MessageItemProps {
  message: ChatMessage;
  toolResults?: Record<string, ToolResult>;
  childrenMessages?: Record<string, ChatMessage[]>;
  expandedTasks?: Set<string>;
  onToggleTaskExpanded?: (toolUseId: string) => void;
  isFirstInGroup?: boolean;
  isLastInGroup?: boolean;
  isStreaming?: boolean;
}

function getToolIcon(toolName: string) {
  switch (toolName) {
    case 'Read':
      return <FileText size={15} />;
    case 'Edit':
    case 'MultiEdit':
      return <Edit size={15} />;
    case 'Bash':
      return <Terminal size={15} />;
    case 'Grep':
    case 'Glob':
      return <Search size={15} />;
    case 'LS':
      return <List size={15} />;
    case 'TodoRead':
    case 'TodoWrite':
      return <CheckSquare size={15} />;
    case 'WebSearch':
      return <Globe size={15} />;
    case 'WebFetch':
      return <ExternalLink size={15} />;
    case 'Task':
      return <Play size={15} />;
    case 'exit_plan_mode':
      return <ClipboardList size={15} />;
    case 'Write':
      return <FileEdit size={15} />;
    default:
      return <Settings size={15} />;
  }
}

// markdownComponents imported from shared module

/** Get the canonical tool group name for merging consecutive calls */
function getToolGroupName(toolName: string): string {
  // Map tool names that should be grouped together
  const groupMap: Record<string, string> = {
    'Grep': 'Search',
    'Glob': 'Search',
    'LS': 'Search',
    'Edit': 'Edit',
    'MultiEdit': 'Edit',
    'TodoRead': 'Todo',
    'TodoWrite': 'Todo',
    'WebSearch': 'Web',
    'WebFetch': 'Web',
  };
  return groupMap[toolName] || toolName;
}

/** Group consecutive content blocks: same-type tool_use blocks are merged */
interface ContentGroup {
  type: 'tool_use' | 'other';
  toolName?: string; // canonical group name for tool_use groups
  blocks: any[];
  startIndex: number;
}

function groupContentBlocks(blocks: any[]): ContentGroup[] {
  const groups: ContentGroup[] = [];

  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];

    if (block.type === 'tool_use') {
      const groupName = getToolGroupName(block.name);
      const lastGroup = groups[groups.length - 1];

      if (lastGroup && lastGroup.type === 'tool_use' && lastGroup.toolName === groupName) {
        lastGroup.blocks.push(block);
      } else {
        groups.push({ type: 'tool_use', toolName: groupName, blocks: [block], startIndex: i });
      }
    } else {
      const lastGroup = groups[groups.length - 1];
      if (lastGroup && lastGroup.type === 'other') {
        lastGroup.blocks.push(block);
      } else {
        groups.push({ type: 'other', blocks: [block], startIndex: i });
      }
    }
  }

  return groups;
}

/** Renders a group of consecutive same-type tool calls with a merged summary */
function ToolGroup({
  toolName,
  toolBlocks,
  toolResults: results,
  workingDirectory,
  childrenMessages,
  expandedTasks,
  onToggleTaskExpanded,
  isStreaming,
}: {
  toolName: string;
  toolBlocks: any[];
  toolResults: Record<string, ToolResult>;
  workingDirectory?: string;
  childrenMessages?: Record<string, ChatMessage[]>;
  expandedTasks?: Set<string>;
  onToggleTaskExpanded?: (toolUseId: string) => void;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const count = toolBlocks.length;

  // Check if any tool in group is still loading
  const anyLoading = toolBlocks.some(b => {
    const r = results[b.id];
    return !r || r.status === 'pending';
  });

  // Generate group summary label
  const getGroupLabel = (): string => {
    switch (toolName) {
      case 'Read': return `Read ${count} files`;
      case 'Edit': return `${count} edits`;
      case 'Search': return `${count} searches`;
      case 'Bash': return `${count} commands`;
      case 'Write': return `Wrote ${count} files`;
      case 'Web': return `${count} web requests`;
      case 'Todo': return `${count} todo operations`;
      default: return `${count} ${toolName} calls`;
    }
  };

  return (
    <div className="flex gap-2 items-start">
      <div className={`w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative ${anyLoading && isStreaming ? 'animate-pulse' : ''}`}>
        {getToolIcon(toolBlocks[0].name)}
      </div>
      <div className="flex-1 flex flex-col min-w-0 break-words">
        {/* Group summary header */}
        <div
          className="flex items-center gap-1 cursor-pointer select-none"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <ChevronRight
            size={12}
            className={`text-muted-foreground transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
          />
          <span className="text-sm font-mono text-foreground">
            <span className="font-semibold">{getGroupLabel()}</span>
          </span>
        </div>

        {/* Expanded: show each tool individually */}
        {isExpanded && (
          <div className="mt-1 ml-1 flex flex-col gap-2 border-l border-border pl-3">
            {toolBlocks.map((block: any, i: number) => {
              const result = results[block.id];
              return (
                <ToolUseRenderer
                  key={block.id}
                  toolUse={block}
                  toolResult={result}
                  toolResults={results}
                  workingDirectory={workingDirectory}
                  childrenMessages={childrenMessages}
                  expandedTasks={expandedTasks}
                  onToggleTaskExpanded={onToggleTaskExpanded}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function MessageItem({ 
  message, 
  toolResults = {}, 
  childrenMessages = {}, 
  expandedTasks = new Set(), 
  onToggleTaskExpanded,
  isFirstInGroup = true, 
  isLastInGroup = true,
  isStreaming = false
}: MessageItemProps) {
  const [copiedBlocks, setCopiedBlocks] = useState<Set<string>>(new Set());
  const [isUserMessageExpanded, setIsUserMessageExpanded] = useState(false);

  const copyContent = async (content: string, blockId: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedBlocks(prev => new Set(prev).add(blockId));
      setTimeout(() => {
        setCopiedBlocks(prev => {
          const next = new Set(prev);
          next.delete(blockId);
          return next;
        });
      }, 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Handle user messages
  if (message.type === 'user') {
    const content = typeof message.content === 'string' 
      ? message.content 
      : Array.isArray(message.content) 
        ? message.content.filter((block: any) => block.type === 'text').map((block: any) => block.text).join('\n')
        : '';
    
    const lines = content.split('\n');
    const shouldShowExpandButton = lines.length > 8;
    const displayLines = isUserMessageExpanded ? lines : lines.slice(0, 8);
    const hiddenLinesCount = lines.length - 8;
    const displayContent = displayLines.join('\n');
    
    return (
      <div className="flex justify-end w-full my-1">
        <div className="relative bg-card text-card-foreground border border-border rounded-xl p-3 max-w-[80%] min-w-[100px]">
          {shouldShowExpandButton && (
            <button
              onClick={() => setIsUserMessageExpanded(!isUserMessageExpanded)}
              className="absolute top-2 right-2 w-6 h-6 border-none bg-transparent text-neutral-600 cursor-pointer flex items-center justify-center p-0 z-10 hover:text-neutral-900"
              aria-label={isUserMessageExpanded ? "Show fewer lines" : "Show all lines"}
            >
              {isUserMessageExpanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          )}
          <div className="text-sm leading-relaxed text-foreground whitespace-pre-wrap break-words">
            {displayContent}
            {!isUserMessageExpanded && shouldShowExpandButton && (
              <span className="text-muted-foreground italic">
                {'\n'}... +{hiddenLinesCount} lines
              </span>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Handle assistant messages with timeline
  if (message.type === 'assistant') {
    const renderContent = () => {
      if (typeof message.content === 'string') {
        return (
            <div className="flex gap-2 items-start">
              <div className="w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative">
                <div className="mt-1 w-2.5 h-2.5 bg-foreground rounded-full" />
              </div>
              <div className="flex-1 min-w-0 prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown components={markdownComponents}>{message.content}</ReactMarkdown>
            </div>
          </div>
        );
      }

      if (Array.isArray(message.content)) {
        // Group consecutive same-type tool_use blocks
        const groups = groupContentBlocks(message.content);

        return groups.map((group, groupIndex) => {
          // Non-tool blocks: render individually
          if (group.type !== 'tool_use') {
            return group.blocks.map((block: any, i: number) => {
              const blockId = `${message.messageId}-${group.startIndex + i}`;

              if (block.type === 'text') {
                return (
                  <div key={blockId} className="flex gap-2 items-start">
                    <div className="w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative">
                      <div className="mt-1 w-2.5 h-2.5 bg-foreground rounded-full" />
                    </div>
                    <div className="flex-1 min-w-0 prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown components={markdownComponents}>{block.text}</ReactMarkdown>
                    </div>
                  </div>
                );
              }

              if (block.type === 'thinking') {
                return (
                  <details key={blockId} className="mb-1">
                    <summary className="cursor-pointer text-xs text-muted-foreground italic select-none hover:text-foreground transition-colors">
                      Thinking
                    </summary>
                    <div className="mt-1 flex-1 min-w-0 prose prose-sm max-w-none italic text-muted-foreground dark:prose-invert pl-4 border-l border-muted">
                      <ReactMarkdown components={markdownComponents}>{block.thinking}</ReactMarkdown>
                    </div>
                  </details>
                );
              }

              // Default: render as JSON
              return (
                <div key={blockId} className="flex gap-2 items-start">
                  <div className="w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative">
                    <Code size={15} />
                  </div>
                  <div className="flex-1 text-sm leading-relaxed text-foreground min-w-0 break-words">
                    <JsonViewer data={block} />
                  </div>
                </div>
              );
            });
          }

          // Tool use group: single tool or multiple consecutive same-type tools
          const toolBlocks = group.blocks;
          const toolName = group.toolName!;
          const groupKey = `${message.messageId}-toolgroup-${groupIndex}`;

          if (toolBlocks.length === 1) {
            // Single tool: render directly (ToolUseRenderer handles its own collapse)
            const block = toolBlocks[0];
            const result = toolResults[block.id];
            const isLoading = !result || result.status === 'pending';
            const shouldBlink = isLoading && isStreaming;

            return (
              <div key={groupKey} className="flex gap-2 items-start">
                <div className={`w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative ${shouldBlink ? 'animate-pulse' : ''}`}>
                  {getToolIcon(block.name)}
                </div>
                <div className="flex-1 flex flex-col gap-2 min-w-0 break-words">
                  <ToolUseRenderer
                    toolUse={block}
                    toolResult={result}
                    toolResults={toolResults}
                    workingDirectory={message.workingDirectory}
                    childrenMessages={childrenMessages}
                    expandedTasks={expandedTasks}
                    onToggleTaskExpanded={onToggleTaskExpanded}
                  />
                </div>
              </div>
            );
          }

          // Multiple consecutive same-type tools: render as collapsed group
          return (
            <ToolGroup
              key={groupKey}
              toolName={toolName}
              toolBlocks={toolBlocks}
              toolResults={toolResults}
              workingDirectory={message.workingDirectory}
              childrenMessages={childrenMessages}
              expandedTasks={expandedTasks}
              onToggleTaskExpanded={onToggleTaskExpanded}
              isStreaming={isStreaming}
            />
          );
        });
      }

      // Fallback
      return (
        <div className="flex gap-2 items-start">
          <div className="w-4 h-5 flex-shrink-0 flex items-center justify-center text-foreground relative">
            <div className="w-2.5 h-2.5 bg-foreground rounded-full" />
          </div>
          <div className="flex-1 text-sm leading-relaxed text-foreground min-w-0 break-words">
            <JsonViewer data={message.content} />
          </div>
        </div>
      );
    };

    return (
      <div className="relative w-full flex flex-col gap-3 my-1">
        {renderContent()}
      </div>
    );
  }

  // Handle error messages
  if (message.type === 'error') {
    return (
      <div className="w-full my-2">
        <div className="text-red-600 text-sm p-3 bg-red-50 rounded-md border border-red-200">
          {String(message.content)}
        </div>
      </div>
    );
  }

  // Default fallback
  return null;
}

