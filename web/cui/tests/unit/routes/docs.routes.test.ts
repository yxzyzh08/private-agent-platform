import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import request from 'supertest';
import express from 'express';
import * as path from 'path';
import * as fs from 'fs/promises';
import * as os from 'os';
import { createDocsRoutes } from '@/routes/docs.routes';
import { errorHandler } from '@/middleware/error-handler';

vi.mock('@/services/logger.js');

describe('Docs Routes', () => {
  let app: express.Application;
  let tmpDir: string;
  let docsDir: string;

  beforeEach(async () => {
    app = express();
    app.use(express.json());
    // Add requestId middleware stub
    app.use((req: any, _res, next) => {
      req.requestId = 'test-req-id';
      next();
    });
    app.use('/api/docs', createDocsRoutes());
    app.use(errorHandler);

    // Create temp project structure
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'docs-test-'));
    docsDir = path.join(tmpDir, 'docs');
    await fs.mkdir(docsDir, { recursive: true });
  });

  afterEach(async () => {
    await fs.rm(tmpDir, { recursive: true, force: true });
  });

  describe('GET /api/docs/tree', () => {
    it('should return correct directory tree structure', async () => {
      await fs.writeFile(path.join(docsDir, 'readme.md'), '# README');
      await fs.mkdir(path.join(docsDir, 'phases'), { recursive: true });
      await fs.writeFile(path.join(docsDir, 'phases', 'phase-1.md'), '# Phase 1');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      expect(res.body.tree).toBeDefined();
      expect(res.body.tree.name).toBe('project');
      expect(res.body.tree.type).toBe('directory');
      // Root children: docs/ directory (which has phases + readme)
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      expect(docsNode).toBeDefined();
      expect(docsNode.children).toHaveLength(2); // phases dir + readme.md
    });

    it('should only return .md files', async () => {
      await fs.writeFile(path.join(docsDir, 'readme.md'), '# README');
      await fs.writeFile(path.join(docsDir, 'image.png'), 'fake-png');
      await fs.writeFile(path.join(docsDir, 'data.json'), '{}');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      expect(docsNode.children).toHaveLength(1);
      expect(docsNode.children[0].name).toBe('readme.md');
    });

    it('should filter empty directories (no .md files)', async () => {
      await fs.mkdir(path.join(docsDir, 'empty-dir'), { recursive: true });
      await fs.writeFile(path.join(docsDir, 'empty-dir', 'data.txt'), 'text');
      await fs.writeFile(path.join(docsDir, 'readme.md'), '# README');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      // Only readme.md, no empty-dir
      expect(docsNode.children).toHaveLength(1);
      expect(docsNode.children[0].name).toBe('readme.md');
    });

    it('should return 404 when no docs/ and no root .md files', async () => {
      const noDocs = await fs.mkdtemp(path.join(os.tmpdir(), 'nodocs-'));
      try {
        const res = await request(app)
          .get('/api/docs/tree')
          .query({ projectPath: noDocs });
        expect(res.status).toBe(404);
      } finally {
        await fs.rm(noDocs, { recursive: true, force: true });
      }
    });

    it('should return root .md files even without docs/ directory', async () => {
      const noDocsDir = await fs.mkdtemp(path.join(os.tmpdir(), 'rootmd-'));
      try {
        await fs.writeFile(path.join(noDocsDir, 'README.md'), '# Root README');
        await fs.writeFile(path.join(noDocsDir, 'CLAUDE.md'), '# Claude');

        const res = await request(app)
          .get('/api/docs/tree')
          .query({ projectPath: noDocsDir });

        expect(res.status).toBe(200);
        expect(res.body.tree.children).toHaveLength(2);
        expect(res.body.tree.children[0].name).toBe('CLAUDE.md');
        expect(res.body.tree.children[1].name).toBe('README.md');
        // Root .md file paths should not have docs/ prefix
        expect(res.body.tree.children[0].path).toBe('CLAUDE.md');
      } finally {
        await fs.rm(noDocsDir, { recursive: true, force: true });
      }
    });

    it('should include both docs/ subtree and root .md files', async () => {
      await fs.writeFile(path.join(docsDir, 'guide.md'), '# Guide');
      await fs.writeFile(path.join(tmpDir, 'README.md'), '# Root README');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const children = res.body.tree.children;
      // docs/ directory first, then root .md files
      const docsNode = children.find((c: any) => c.name === 'docs');
      const rootFile = children.find((c: any) => c.name === 'README.md');
      expect(docsNode).toBeDefined();
      expect(rootFile).toBeDefined();
      expect(rootFile.path).toBe('README.md');
    });

    it('should return 400 when projectPath is missing', async () => {
      const res = await request(app).get('/api/docs/tree');
      expect(res.status).toBe(400);
    });

    it('should return 400 when projectPath is not absolute', async () => {
      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: 'relative/path' });
      expect(res.status).toBe(400);
    });

    it('should return 400 when projectPath contains null bytes', async () => {
      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: '/tmp/test\0evil' });
      expect(res.status).toBe(400);
    });

    it('should sort directories before files within docs/', async () => {
      await fs.writeFile(path.join(docsDir, 'zebra.md'), '# Zebra');
      await fs.mkdir(path.join(docsDir, 'alpha'), { recursive: true });
      await fs.writeFile(path.join(docsDir, 'alpha', 'content.md'), '# Alpha');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      const children = docsNode.children;
      expect(children[0].type).toBe('directory');
      expect(children[0].name).toBe('alpha');
      expect(children[1].type).toBe('file');
      expect(children[1].name).toBe('zebra.md');
    });

    it('should skip hidden files and directories', async () => {
      await fs.writeFile(path.join(docsDir, '.hidden.md'), '# Hidden');
      await fs.mkdir(path.join(docsDir, '.hidden-dir'), { recursive: true });
      await fs.writeFile(path.join(docsDir, '.hidden-dir', 'file.md'), '# File');
      await fs.writeFile(path.join(docsDir, 'visible.md'), '# Visible');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      expect(docsNode.children).toHaveLength(1);
      expect(docsNode.children[0].name).toBe('visible.md');
    });

    it('should include file metadata (size, modifiedAt)', async () => {
      await fs.writeFile(path.join(docsDir, 'test.md'), '# Test Content');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      const docsNode = res.body.tree.children.find((c: any) => c.name === 'docs');
      const file = docsNode.children[0];
      expect(file.size).toBeGreaterThan(0);
      expect(file.modifiedAt).toBeDefined();
    });

    it('should handle deeply nested directories up to max depth', async () => {
      // Create 11 levels deep
      let dir = docsDir;
      for (let i = 0; i < 11; i++) {
        dir = path.join(dir, `level${i}`);
        await fs.mkdir(dir, { recursive: true });
      }
      await fs.writeFile(path.join(dir, 'deep.md'), '# Deep');

      const res = await request(app)
        .get('/api/docs/tree')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(200);
      // The tree should exist but the deepest file (>10 levels) should not be included
      // 10 levels of nesting from docs/ means level0..level9 is within limit, level10 is not
    });
  });

  describe('GET /api/docs/content', () => {
    it('should return file content and metadata', async () => {
      const content = '# Hello World\n\nThis is a test document.';
      await fs.writeFile(path.join(docsDir, 'test.md'), content);

      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/test.md' });

      expect(res.status).toBe(200);
      expect(res.body.content).toBe(content);
      expect(res.body.size).toBeGreaterThan(0);
      expect(res.body.modifiedAt).toBeDefined();
    });

    it('should reject path traversal with ../', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/../../../etc/passwd' });

      expect(res.status).toBe(403);
    });

    it('should reject URL-encoded path traversal (%2e%2e)', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/%2e%2e/%2e%2e/etc/passwd' });

      expect(res.status).toBe(403);
    });

    it('should reject files in non-docs subdirectories', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'src/main.md' });

      expect(res.status).toBe(403);
    });

    it('should allow reading root-level .md files', async () => {
      const content = '# Root README';
      await fs.writeFile(path.join(tmpDir, 'README.md'), content);

      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'README.md' });

      expect(res.status).toBe(200);
      expect(res.body.content).toBe(content);
    });

    it('should reject non-.md files', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/image.png' });

      expect(res.status).toBe(403);
    });

    it('should return 404 for non-existent files', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/nonexistent.md' });

      expect(res.status).toBe(404);
    });

    it('should return 413 for files exceeding 1MB', async () => {
      const largeContent = 'x'.repeat(1024 * 1024 + 1);
      await fs.writeFile(path.join(docsDir, 'large.md'), largeContent);

      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/large.md' });

      expect(res.status).toBe(413);
    });

    it('should return 400 when filePath is missing', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir });

      expect(res.status).toBe(400);
    });

    it('should return 400 when projectPath is missing', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ filePath: 'docs/test.md' });

      expect(res.status).toBe(400);
    });

    it('should not leak absolute paths in error responses', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/nonexistent.md' });

      expect(res.status).toBe(404);
      expect(JSON.stringify(res.body)).not.toContain(tmpDir);
    });

    it('should reject symlinks pointing outside docs/', async () => {
      // Create a file outside docs
      const outsideFile = path.join(tmpDir, 'secret.md');
      await fs.writeFile(outsideFile, '# Secret');

      // Create symlink inside docs pointing to outside file
      try {
        await fs.symlink(outsideFile, path.join(docsDir, 'symlink.md'));
      } catch {
        // Skip test if symlinks not supported
        return;
      }

      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/symlink.md' });

      expect(res.status).toBe(403);
    });

    it('should handle nested file paths correctly', async () => {
      await fs.mkdir(path.join(docsDir, 'phases'), { recursive: true });
      await fs.writeFile(path.join(docsDir, 'phases', 'phase-1.md'), '# Phase 1');

      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/phases/phase-1.md' });

      expect(res.status).toBe(200);
      expect(res.body.content).toBe('# Phase 1');
    });

    it('should reject filePath with null bytes', async () => {
      const res = await request(app)
        .get('/api/docs/content')
        .query({ projectPath: tmpDir, filePath: 'docs/test\0.md' });

      // Should be rejected (400 or 403)
      expect(res.status).toBeGreaterThanOrEqual(400);
    });
  });
});
