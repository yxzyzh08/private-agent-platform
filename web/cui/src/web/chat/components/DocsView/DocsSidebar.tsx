import React, { useState } from 'react';
import { Folder, FolderOpen, FileText, ChevronRight } from 'lucide-react';
import type { DocsTreeNode } from '../../types';

interface DocsSidebarProps {
  treeData: DocsTreeNode;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
}

interface TreeNodeProps {
  node: DocsTreeNode;
  depth: number;
  selectedFile: string | null;
  onSelectFile: (path: string) => void;
  defaultExpanded?: boolean;
}

function TreeNode({ node, depth, selectedFile, onSelectFile, defaultExpanded = false }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  if (node.type === 'directory') {
    return (
      <div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center gap-1 py-1 px-1 rounded text-sm hover:bg-accent text-foreground transition-colors"
          style={{ paddingLeft: `${depth * 16 + 4}px` }}
        >
          <ChevronRight
            size={12}
            className={`text-muted-foreground transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
          />
          {isExpanded ? (
            <FolderOpen size={14} className="text-amber-500 flex-shrink-0" />
          ) : (
            <Folder size={14} className="text-amber-500 flex-shrink-0" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <TreeNode
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedFile={selectedFile}
                onSelectFile={onSelectFile}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const isSelected = selectedFile === node.path;

  return (
    <button
      onClick={() => onSelectFile(node.path)}
      className={`w-full flex items-center gap-1 py-1 px-1 rounded text-sm transition-colors ${
        isSelected
          ? 'bg-accent text-accent-foreground font-medium'
          : 'hover:bg-accent/50 text-foreground'
      }`}
      style={{ paddingLeft: `${depth * 16 + 20}px` }}
    >
      <FileText size={14} className="text-muted-foreground flex-shrink-0" />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

export function DocsSidebar({ treeData, selectedFile, onSelectFile }: DocsSidebarProps) {
  return (
    <div className="h-full overflow-y-auto py-2 border-r border-border">
      {treeData.children && treeData.children.length > 0 ? (
        <TreeNode
          node={treeData}
          depth={0}
          selectedFile={selectedFile}
          onSelectFile={onSelectFile}
          defaultExpanded={true}
        />
      ) : (
        <div className="p-4 text-sm text-muted-foreground">No documents found</div>
      )}
    </div>
  );
}
