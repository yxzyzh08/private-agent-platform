import React, { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import { createMarkdownComponents } from '../shared/markdownComponents';
import { MermaidBlock } from './MermaidBlock';

interface DocsContentProps {
  content: string | null;
  loading: boolean;
  filePath: string | null;
  size?: number;
  modifiedAt?: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function DocsContent({ content, loading, filePath, size, modifiedAt }: DocsContentProps) {
  const docsMarkdownComponents = useMemo(
    () => createMarkdownComponents({ mermaidRenderer: MermaidBlock }),
    []
  );

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
          Loading...
        </div>
      </div>
    );
  }

  if (!filePath || content === null) {
    return null; // Parent handles empty state
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      {/* File metadata header */}
      <div className="mb-4 pb-2 border-b border-border">
        <div className="text-xs text-muted-foreground flex items-center gap-3">
          <span className="font-mono">{filePath}</span>
          {size !== undefined && <span>{formatFileSize(size)}</span>}
          {modifiedAt && <span>{formatDate(modifiedAt)}</span>}
        </div>
      </div>

      {/* Markdown content */}
      <div className="prose prose-sm dark:prose-invert max-w-[800px]">
        <ReactMarkdown components={docsMarkdownComponents}>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
