import { Router, Request, Response, NextFunction } from 'express';
import * as path from 'path';
import * as fs from 'fs/promises';
import { CUIError } from '@/types/index.js';
import { RequestWithRequestId } from '@/types/express.js';
import { createLogger } from '@/services/logger.js';

const MAX_DEPTH = 10;
const MAX_FILES = 1000;
const MAX_FILE_SIZE = 1 * 1024 * 1024; // 1MB

export interface DocsTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  modifiedAt?: string;
  children?: DocsTreeNode[];
}

interface TreeScanResult {
  node: DocsTreeNode | null;
  fileCount: number;
  truncated: boolean;
}

export function createDocsRoutes(): Router {
  const router = Router();
  const logger = createLogger('DocsRoutes');

  function validateProjectPath(projectPath: string | undefined): string {
    if (!projectPath) {
      throw new CUIError('MISSING_PARAM', 'projectPath query parameter is required', 400);
    }
    if (!projectPath.startsWith('/')) {
      throw new CUIError('INVALID_PARAM', 'projectPath must be an absolute path', 400);
    }
    if (projectPath.includes('\0')) {
      throw new CUIError('INVALID_PARAM', 'projectPath contains invalid characters', 400);
    }
    return projectPath;
  }

  function validateFilePath(filePath: string | undefined): string {
    if (!filePath) {
      throw new CUIError('MISSING_PARAM', 'filePath query parameter is required', 400);
    }
    // Decode URI component first to prevent double-encoding bypass
    let decoded: string;
    try {
      decoded = decodeURIComponent(filePath);
    } catch {
      throw new CUIError('INVALID_PARAM', 'filePath contains invalid encoding', 400);
    }
    if (decoded.includes('\0')) {
      throw new CUIError('INVALID_PARAM', 'filePath contains invalid characters', 400);
    }
    if (decoded.includes('..')) {
      throw new CUIError('PATH_TRAVERSAL', `Access denied: ${filePath}`, 403);
    }
    if (!decoded.endsWith('.md')) {
      throw new CUIError('INVALID_FILE_TYPE', `Only .md files are supported: ${filePath}`, 403);
    }
    // Allow docs/ subtree and root-level .md files (no subdirectory)
    const isDocsPath = decoded.startsWith('docs/');
    const isRootMd = !decoded.includes('/');
    if (!isDocsPath && !isRootMd) {
      throw new CUIError('INVALID_PATH', `Access denied: ${filePath}`, 403);
    }
    return decoded;
  }

  async function scanDirectory(
    dirPath: string,
    relativePath: string,
    depth: number,
    currentCount: number
  ): Promise<TreeScanResult> {
    if (depth > MAX_DEPTH) {
      return { node: null, fileCount: currentCount, truncated: false };
    }

    let entries;
    try {
      entries = await fs.readdir(dirPath, { withFileTypes: true });
    } catch {
      return { node: null, fileCount: currentCount, truncated: false };
    }

    // Sort: directories first, then files, each alphabetically
    entries.sort((a, b) => {
      if (a.isDirectory() && !b.isDirectory()) return -1;
      if (!a.isDirectory() && b.isDirectory()) return 1;
      return a.name.localeCompare(b.name);
    });

    const children: DocsTreeNode[] = [];
    let fileCount = currentCount;
    let truncated = false;

    for (const entry of entries) {
      // Skip hidden files/directories
      if (entry.name.startsWith('.')) continue;

      const entryPath = path.join(dirPath, entry.name);
      const entryRelativePath = relativePath ? `${relativePath}/${entry.name}` : entry.name;

      if (entry.isSymbolicLink()) continue;

      if (entry.isDirectory()) {
        const result = await scanDirectory(entryPath, entryRelativePath, depth + 1, fileCount);
        fileCount = result.fileCount;
        if (result.truncated) truncated = true;
        // Only include directories that contain .md files
        if (result.node && result.node.children && result.node.children.length > 0) {
          children.push(result.node);
        }
      } else if (entry.isFile() && entry.name.endsWith('.md')) {
        if (fileCount >= MAX_FILES) {
          truncated = true;
          break;
        }
        try {
          const stat = await fs.stat(entryPath);
          children.push({
            name: entry.name,
            path: `docs/${entryRelativePath}`,
            type: 'file',
            size: stat.size,
            modifiedAt: stat.mtime.toISOString(),
          });
          fileCount++;
        } catch {
          // Skip files we can't stat
        }
      }
    }

    if (children.length === 0) {
      return { node: null, fileCount, truncated };
    }

    const dirName = path.basename(dirPath);
    return {
      node: {
        name: dirName,
        path: relativePath ? `docs/${relativePath}` : 'docs',
        type: 'directory',
        children,
      },
      fileCount,
      truncated,
    };
  }

  // Scan root-level .md files (non-recursive)
  async function scanRootMdFiles(projectPath: string): Promise<DocsTreeNode[]> {
    const files: DocsTreeNode[] = [];
    let entries;
    try {
      entries = await fs.readdir(projectPath, { withFileTypes: true });
    } catch {
      return files;
    }
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      if (entry.isSymbolicLink()) continue;
      if (entry.isFile() && entry.name.endsWith('.md')) {
        try {
          const stat = await fs.stat(path.join(projectPath, entry.name));
          files.push({
            name: entry.name,
            path: entry.name,
            type: 'file',
            size: stat.size,
            modifiedAt: stat.mtime.toISOString(),
          });
        } catch {
          // Skip files we can't stat
        }
      }
    }
    files.sort((a, b) => a.name.localeCompare(b.name));
    return files;
  }

  // GET /api/docs/tree — Get document directory tree
  router.get('/tree', async (req: Request & RequestWithRequestId, res: Response, next: NextFunction) => {
    const requestId = req.requestId;
    try {
      const projectPath = validateProjectPath(req.query.projectPath as string);
      const docsPath = path.join(projectPath, 'docs');

      logger.debug('Docs tree request', { requestId, projectPath });

      // Scan root-level .md files
      const rootMdFiles = await scanRootMdFiles(projectPath);

      // Scan docs/ directory (may not exist)
      let docsResult: TreeScanResult = { node: null, fileCount: 0, truncated: false };
      let docsExists = false;
      try {
        const stat = await fs.stat(docsPath);
        if (stat.isDirectory()) {
          docsExists = true;
          docsResult = await scanDirectory(docsPath, '', 0, 0);
        }
      } catch {
        // docs/ doesn't exist — that's fine
      }

      // If neither root md files nor docs/ exist, return 404
      if (rootMdFiles.length === 0 && !docsExists) {
        throw new CUIError('NOT_FOUND', 'No markdown files found', 404);
      }

      // Build combined tree: root node contains root .md files + docs/ subtree
      const children: DocsTreeNode[] = [];

      // Add docs/ subtree first (if it has content)
      if (docsResult.node && docsResult.node.children && docsResult.node.children.length > 0) {
        children.push(docsResult.node);
      }

      // Add root-level .md files
      children.push(...rootMdFiles);

      const tree: DocsTreeNode = {
        name: 'project',
        path: '',
        type: 'directory',
        children,
      };

      const totalFileCount = docsResult.fileCount + rootMdFiles.length;
      const response: { tree: DocsTreeNode; truncated?: boolean } = { tree };
      if (docsResult.truncated) {
        response.truncated = true;
      }

      logger.debug('Docs tree built', { requestId, fileCount: totalFileCount, truncated: docsResult.truncated });
      res.json(response);
    } catch (error) {
      next(error);
    }
  });

  // GET /api/docs/content — Read a specific document file
  router.get('/content', async (req: Request & RequestWithRequestId, res: Response, next: NextFunction) => {
    const requestId = req.requestId;
    try {
      const projectPath = validateProjectPath(req.query.projectPath as string);
      const filePath = validateFilePath(req.query.filePath as string);

      logger.debug('Docs content request', { requestId, filePath });

      const absolutePath = path.resolve(projectPath, filePath);

      let realPath: string;
      try {
        realPath = await fs.realpath(absolutePath);
      } catch {
        throw new CUIError('NOT_FOUND', `File not found: ${filePath}`, 404);
      }

      let realProjectDir: string;
      try {
        realProjectDir = await fs.realpath(projectPath);
      } catch {
        throw new CUIError('NOT_FOUND', 'Project directory does not exist', 404);
      }

      // Root-level .md files: must be directly in project root
      const isRootMd = !filePath.includes('/');
      if (isRootMd) {
        if (path.dirname(realPath) !== realProjectDir) {
          logger.warn('Path traversal attempt detected', { requestId, filePath });
          throw new CUIError('PATH_TRAVERSAL', `Access denied: ${filePath}`, 403);
        }
      } else {
        // docs/ subtree: realpath must be within <projectPath>/docs/
        const docsDir = path.join(projectPath, 'docs');
        let realDocsDir: string;
        try {
          realDocsDir = await fs.realpath(docsDir);
        } catch {
          throw new CUIError('NOT_FOUND', 'docs/ directory does not exist', 404);
        }
        if (!realPath.startsWith(realDocsDir + path.sep) && realPath !== realDocsDir) {
          logger.warn('Path traversal attempt detected', { requestId, filePath });
          throw new CUIError('PATH_TRAVERSAL', `Access denied: ${filePath}`, 403);
        }
      }

      const stat = await fs.stat(realPath);
      if (stat.size > MAX_FILE_SIZE) {
        throw new CUIError('FILE_TOO_LARGE', `File exceeds 1MB limit: ${filePath}`, 413);
      }

      const content = await fs.readFile(realPath, 'utf-8');

      res.json({
        content,
        size: stat.size,
        modifiedAt: stat.mtime.toISOString(),
      });
    } catch (error) {
      next(error);
    }
  });

  return router;
}
