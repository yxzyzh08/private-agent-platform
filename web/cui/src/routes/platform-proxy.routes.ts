/**
 * Platform API proxy routes (Phase 1D).
 *
 * Proxies frontend requests to the FastAPI backend, avoiding CORS issues.
 * Special handling for SSE (text/event-stream) — no buffering, immediate flush.
 */
import { Router, Request, Response } from 'express';
import { createLogger } from '@/services/logger.js';

const PLATFORM_API_URL =
  process.env.PLATFORM_API_URL || 'http://localhost:8000';

export function createPlatformProxyRoutes(): Router {
  const router = Router();
  const logger = createLogger('PlatformProxy');

  // --- Helper ---

  async function proxyRequest(
    req: Request,
    res: Response,
    method: string,
    backendPath: string,
    body?: unknown
  ): Promise<void> {
    try {
      const options: RequestInit = {
        method,
        headers: { 'Content-Type': 'application/json' },
      };
      if (body) {
        options.body = JSON.stringify(body);
      }

      const resp = await fetch(`${PLATFORM_API_URL}${backendPath}`, options);
      const data = await resp.json().catch(() => ({}));
      res.status(resp.status).json(data);
    } catch (error) {
      logger.error('Platform proxy error', {
        path: backendPath,
        error: error instanceof Error ? error.message : String(error),
      });
      res.status(502).json({
        error: 'Platform backend unreachable',
        detail: error instanceof Error ? error.message : String(error),
      });
    }
  }

  // --- Project init ---

  router.post('/projects/init', async (req: Request, res: Response) => {
    await proxyRequest(req, res, 'POST', '/api/projects/init', req.body);
  });

  // --- Requirements ---

  router.get(
    '/requirements/:planId',
    async (req: Request, res: Response) => {
      await proxyRequest(
        req,
        res,
        'GET',
        `/api/requirements/${req.params.planId}`
      );
    }
  );

  router.post(
    '/requirements/:planId/abort',
    async (req: Request, res: Response) => {
      await proxyRequest(
        req,
        res,
        'POST',
        `/api/requirements/${req.params.planId}/abort`
      );
    }
  );

  router.post(
    '/requirements/:planId/tasks/:taskId/retry',
    async (req: Request, res: Response) => {
      await proxyRequest(
        req,
        res,
        'POST',
        `/api/requirements/${req.params.planId}/tasks/${req.params.taskId}/retry`,
        req.body
      );
    }
  );

  router.post(
    '/requirements/:planId/tasks/:taskId/skip',
    async (req: Request, res: Response) => {
      await proxyRequest(
        req,
        res,
        'POST',
        `/api/requirements/${req.params.planId}/tasks/${req.params.taskId}/skip`
      );
    }
  );

  // --- SSE proxy (special handling) ---

  router.get(
    '/requirements/:planId/events',
    async (req: Request, res: Response) => {
      const planId = req.params.planId;
      const backendUrl = `${PLATFORM_API_URL}/api/requirements/${planId}/events`;

      try {
        const resp = await fetch(backendUrl);

        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          res.status(resp.status).json(data);
          return;
        }

        // Set SSE headers
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('X-Accel-Buffering', 'no');
        res.flushHeaders();

        // Stream body to client
        const reader = resp.body?.getReader();
        if (!reader) {
          res.status(502).json({ error: 'No response body from backend' });
          return;
        }

        const decoder = new TextDecoder();
        let closed = false;

        // Cleanup on client disconnect
        req.on('close', () => {
          closed = true;
          reader.cancel().catch(() => {});
          logger.debug('SSE client disconnected', { planId });
        });

        // Read and forward chunks
        try {
          while (!closed) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            res.write(chunk);
          }
        } catch (error) {
          if (!closed) {
            logger.error('SSE proxy stream error', {
              planId,
              error: error instanceof Error ? error.message : String(error),
            });
          }
        } finally {
          if (!closed) {
            res.end();
          }
        }
      } catch (error) {
        logger.error('SSE proxy connection error', {
          planId,
          error: error instanceof Error ? error.message : String(error),
        });
        if (!res.headersSent) {
          res.status(502).json({
            error: 'Platform backend unreachable',
            detail: error instanceof Error ? error.message : String(error),
          });
        }
      }
    }
  );

  return router;
}
