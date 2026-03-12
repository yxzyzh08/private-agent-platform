import React from 'react';
import { CodeHighlight } from '../CodeHighlight';

export function createMarkdownComponents(opts?: { mermaidRenderer?: React.ComponentType<{ code: string }> }) {
  return {
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : 'text';

      if (!inline && match) {
        // Mermaid code blocks: delegate to MermaidBlock if provided
        if (language === 'mermaid' && opts?.mermaidRenderer) {
          const MermaidRenderer = opts.mermaidRenderer;
          return <MermaidRenderer code={String(children).replace(/\n$/, '')} />;
        }

        return (
          <CodeHighlight
            code={String(children).replace(/\n$/, '')}
            language={language}
            className="bg-neutral-900 rounded-md overflow-hidden max-w-full box-border"
          />
        );
      }

      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
  };
}

// Default markdown components (without mermaid) for backward compatibility
export const markdownComponents = createMarkdownComponents();
