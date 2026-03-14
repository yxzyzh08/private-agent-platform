import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, FileText, Clock, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { api } from '../../services/api';
import { DocsSidebar } from './DocsSidebar';
import { DocsContent } from './DocsContent';
import type { DocsTreeNode } from '../../types';
import { useConversations } from '../../contexts/ConversationsContext';

// Flatten tree to get all file nodes
function flattenFiles(node: DocsTreeNode): DocsTreeNode[] {
  const files: DocsTreeNode[] = [];
  if (node.type === 'file') {
    files.push(node);
  }
  if (node.children) {
    for (const child of node.children) {
      files.push(...flattenFiles(child));
    }
  }
  return files;
}

export function DocsView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { selectedProjectPath: contextProjectPath } = useConversations();

  // URL param takes priority (new tab), then fall back to context (same tab)
  const selectedProjectPath = searchParams.get('project') || contextProjectPath;

  const [treeData, setTreeData] = useState<DocsTreeNode | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(searchParams.get('file'));
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileMeta, setFileMeta] = useState<{ size?: number; modifiedAt?: string }>({});
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // Load tree when project path changes
  useEffect(() => {
    if (!selectedProjectPath) {
      setTreeData(null);
      return;
    }

    let cancelled = false;
    setTreeLoading(true);
    setTreeError(null);

    api.getDocsTree(selectedProjectPath)
      .then(({ tree }) => {
        if (!cancelled) setTreeData(tree);
      })
      .catch((err) => {
        if (!cancelled) {
          if (err.message?.includes('404') || err.message?.includes('does not exist')) {
            setTreeError('nodocs');
          } else {
            setTreeError(err.message || 'Failed to load docs');
          }
        }
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false);
      });

    return () => { cancelled = true; };
  }, [selectedProjectPath]);

  // Load file content when selected file changes
  useEffect(() => {
    if (!selectedFile || !selectedProjectPath) {
      setFileContent(null);
      setFileMeta({});
      return;
    }

    let cancelled = false;
    setFileLoading(true);

    api.getDocsContent(selectedProjectPath, selectedFile)
      .then(({ content, size, modifiedAt }) => {
        if (!cancelled) {
          setFileContent(content);
          setFileMeta({ size, modifiedAt });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          if (err.message?.includes('404') || err.message?.includes('not found')) {
            // File doesn't exist, clear URL and show welcome
            setSelectedFile(null);
            const projectParam = searchParams.get('project');
            setSearchParams(projectParam ? { project: projectParam } : {}, { replace: true });
          } else {
            setFileContent(null);
            setFileMeta({});
          }
        }
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });

    return () => { cancelled = true; };
  }, [selectedFile, selectedProjectPath, setSearchParams]);

  // Sync URL with selected file
  const handleSelectFile = useCallback((filePath: string) => {
    setSelectedFile(filePath);
    const projectParam = searchParams.get('project');
    const params: Record<string, string> = { file: filePath };
    if (projectParam) params.project = projectParam;
    setSearchParams(params, { replace: true });
  }, [searchParams, setSearchParams]);

  // On mount, restore file from URL
  useEffect(() => {
    const fileFromUrl = searchParams.get('file');
    if (fileFromUrl && fileFromUrl !== selectedFile) {
      setSelectedFile(fileFromUrl);
    }
  }, []); // Only on mount

  // Recent files from tree
  const recentFiles = useMemo(() => {
    if (!treeData) return [];
    return flattenFiles(treeData)
      .filter(f => f.modifiedAt)
      .sort((a, b) => new Date(b.modifiedAt!).getTime() - new Date(a.modifiedAt!).getTime())
      .slice(0, 5);
  }, [treeData]);

  const totalFiles = useMemo(() => {
    if (!treeData) return 0;
    return flattenFiles(treeData).length;
  }, [treeData]);

  // Breadcrumb from selected file path
  const breadcrumbs = selectedFile ? selectedFile.split('/') : [];

  // Empty states
  if (!selectedProjectPath) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <FileText size={48} className="mx-auto mb-4 opacity-50" />
          <p className="text-lg font-medium">Please select a project first</p>
          <p className="text-sm mt-1">Go back to Home and select a working directory</p>
          <button
            onClick={() => navigate('/')}
            className="mt-4 px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:opacity-90"
          >
            Go to Home
          </button>
        </div>
      </div>
    );
  }

  if (treeLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-2 text-muted-foreground">
          <div className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
          Loading documentation...
        </div>
      </div>
    );
  }

  if (treeError === 'nodocs') {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <FileText size={48} className="mx-auto mb-4 opacity-50" />
          <p className="text-lg font-medium">No markdown files found</p>
          <p className="text-sm mt-1">This project has no .md files in root or docs/ directory</p>
          <button
            onClick={() => navigate('/')}
            className="mt-4 px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:opacity-90"
          >
            Back to Home
          </button>
        </div>
      </div>
    );
  }

  if (treeError) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center text-red-500">
          <p>Error loading docs: {treeError}</p>
          <button
            onClick={() => navigate('/')}
            className="mt-4 px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:opacity-90"
          >
            Back to Home
          </button>
        </div>
      </div>
    );
  }

  // Project short name
  const projectName = selectedProjectPath.split('/').filter(Boolean).pop() || 'Project';

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-background">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft size={16} />
          Home
        </button>
        <div className="text-muted-foreground">/</div>
        {breadcrumbs.length > 0 ? (
          breadcrumbs.map((part, i) => (
            <React.Fragment key={i}>
              {i > 0 && <div className="text-muted-foreground">/</div>}
              <span className={`text-sm ${i === breadcrumbs.length - 1 ? 'text-foreground font-medium' : 'text-muted-foreground'}`}>
                {part}
              </span>
            </React.Fragment>
          ))
        ) : (
          <span className="text-sm text-muted-foreground">Docs</span>
        )}
        <div className="flex-1" />
        <span className="text-xs text-muted-foreground">{projectName}</span>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className={`flex-shrink-0 overflow-hidden transition-[width] duration-200 ${sidebarCollapsed ? 'w-0' : 'w-[220px]'}`}>
          {treeData && (
            <DocsSidebar
              treeData={treeData}
              selectedFile={selectedFile}
              onSelectFile={handleSelectFile}
            />
          )}
        </div>
        {/* Sidebar toggle */}
        <div className="flex-shrink-0 border-r border-border flex flex-col items-center pt-2">
          <button
            type="button"
            onClick={() => setSidebarCollapsed(prev => !prev)}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        {/* Content area */}
        {selectedFile ? (
          <DocsContent
            content={fileContent}
            loading={fileLoading}
            filePath={selectedFile}
            size={fileMeta.size}
            modifiedAt={fileMeta.modifiedAt}
          />
        ) : (
          /* Welcome / empty state */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center max-w-md">
              <FileText size={48} className="mx-auto mb-4 text-muted-foreground opacity-50" />
              <p className="text-lg font-medium text-foreground mb-2">Project Documentation</p>
              <p className="text-sm text-muted-foreground mb-4">
                {totalFiles} document{totalFiles !== 1 ? 's' : ''} found
              </p>
              {recentFiles.length > 0 && (
                <div className="text-left">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1">
                    <Clock size={12} />
                    Recently modified
                  </p>
                  <div className="space-y-1">
                    {recentFiles.map((file) => (
                      <button
                        key={file.path}
                        onClick={() => handleSelectFile(file.path)}
                        className="w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent transition-colors flex items-center gap-2"
                      >
                        <FileText size={14} className="text-muted-foreground flex-shrink-0" />
                        <span className="truncate text-foreground">{file.name}</span>
                        {file.modifiedAt && (
                          <span className="text-xs text-muted-foreground ml-auto flex-shrink-0">
                            {new Date(file.modifiedAt).toLocaleDateString()}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
