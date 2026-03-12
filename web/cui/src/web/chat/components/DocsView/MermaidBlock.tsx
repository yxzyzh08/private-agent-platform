import React, { useEffect, useRef, useState } from 'react';
import DOMPurify from 'dompurify';
import { useTheme } from '../../hooks/useTheme';
import { CodeHighlight } from '../CodeHighlight';

interface MermaidBlockProps {
  code: string;
}

let mermaidInstance: typeof import('mermaid')['default'] | null = null;
let mermaidLoadPromise: Promise<typeof import('mermaid')['default']> | null = null;
let lastTheme: string | null = null;

async function loadMermaid(): Promise<typeof import('mermaid')['default']> {
  if (mermaidInstance) return mermaidInstance;
  if (mermaidLoadPromise) return mermaidLoadPromise;
  mermaidLoadPromise = import('mermaid').then(m => {
    mermaidInstance = m.default;
    return mermaidInstance;
  });
  return mermaidLoadPromise;
}

let renderCounter = 0;

export function MermaidBlock({ code }: MermaidBlockProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { mode } = useTheme();

  useEffect(() => {
    let cancelled = false;

    async function render() {
      setLoading(true);
      setError(null);

      try {
        const mermaid = await loadMermaid();
        if (cancelled) return;

        const currentTheme = mode === 'dark' ? 'dark' : 'default';
        if (lastTheme !== currentTheme) {
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: currentTheme,
          });
          lastTheme = currentTheme;
        }

        const id = `mermaid-${++renderCounter}`;
        const { svg } = await mermaid.render(id, code);
        if (cancelled) return;

        const sanitizedSvg = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true } });

        if (containerRef.current) {
          containerRef.current.innerHTML = sanitizedSvg;
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Mermaid rendering failed');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    render();
    return () => { cancelled = true; };
  }, [code, mode]);

  if (error) {
    return (
      <div className="my-2">
        <div className="text-xs text-amber-600 dark:text-amber-400 mb-1">Mermaid rendering error: {error}</div>
        <CodeHighlight code={code} language="mermaid" className="bg-neutral-900 rounded-md overflow-hidden max-w-full box-border" />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="my-2 flex items-center gap-2 text-muted-foreground text-sm">
        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
        Rendering diagram...
      </div>
    );
  }

  return <div ref={containerRef} className="my-2 overflow-x-auto" />;
}
