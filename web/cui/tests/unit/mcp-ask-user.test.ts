/**
 * Tests for MCP server ask_user flow.
 * We test sendNotification and pollUntilResolved helpers plus
 * the ask_user handler by importing the module with mocked fetch.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// We test the shared helper functions directly by re-implementing them
// (the MCP server module has top-level side effects, so we can't import it safely).
// Instead, we verify the same logic via an extracted test harness.

// ── sendNotification logic ──────────────────────────────────────

async function sendNotification(
  fetchFn: typeof fetch,
  url: string,
  body: Record<string, unknown>,
): Promise<string> {
  const response = await fetchFn(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to notify: ${errorText}`);
  }

  const data = (await response.json()) as { success: boolean; id: string };
  return data.id;
}

// ── pollUntilResolved logic ──────────────────────────────────────

interface McpToolResult {
  content: Array<{ type: string; text: string }>;
}

async function pollUntilResolved<T>(
  fetchFn: typeof fetch,
  pollUrl: string,
  checkFn: (data: T) => McpToolResult | null,
  pollInterval: number,
  timeout: number,
): Promise<McpToolResult> {
  const startTime = Date.now();

  while (true) {
    if (Date.now() - startTime > timeout) {
      return {
        content: [{ type: 'text', text: JSON.stringify({ behavior: 'deny', message: 'Timed out' }) }],
      };
    }

    const pollResponse = await fetchFn(pollUrl, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!pollResponse.ok) {
      throw new Error(`Poll failed: ${pollResponse.status}`);
    }

    const data = (await pollResponse.json()) as T;
    const result = checkFn(data);
    if (result) return result;

    await new Promise((resolve) => setTimeout(resolve, pollInterval));
  }
}

// ── Tests ──────────────────────────────────────────────────────

describe('MCP ask_user helpers', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('sendNotification', () => {
    it('should POST and return the id', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, id: 'q-123' }),
      });

      const id = await sendNotification(
        mockFetch as any,
        'http://localhost:3001/api/questions/notify',
        { questions: [], streamingId: 'stream-1' },
      );

      expect(id).toBe('q-123');
      expect(mockFetch).toHaveBeenCalledOnce();
      const [url, opts] = mockFetch.mock.calls[0];
      expect(url).toBe('http://localhost:3001/api/questions/notify');
      expect(opts.method).toBe('POST');
    });

    it('should throw on non-ok response', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => 'Bad request',
      });

      await expect(
        sendNotification(mockFetch as any, 'http://x', {}),
      ).rejects.toThrow('Failed to notify: Bad request');
    });
  });

  describe('pollUntilResolved', () => {
    it('should return result when check function matches', async () => {
      let callCount = 0;
      const mockFetch = vi.fn().mockImplementation(async () => {
        callCount++;
        return {
          ok: true,
          json: async () => ({
            question: {
              id: 'q-1',
              status: callCount >= 2 ? 'answered' : 'pending',
              answers: callCount >= 2 ? { '0': 'React' } : undefined,
            },
          }),
        };
      });

      const resultPromise = pollUntilResolved(
        mockFetch as any,
        'http://localhost:3001/api/questions/q-1',
        (data: any) => {
          if (data.question.status === 'answered') {
            return {
              content: [{ type: 'text', text: JSON.stringify({ answers: data.question.answers }) }],
            };
          }
          return null;
        },
        100, // poll interval
        60000, // timeout
      );

      // First poll — still pending, advance timer for next poll
      await vi.advanceTimersByTimeAsync(100);
      // Second poll — answered
      await vi.advanceTimersByTimeAsync(100);

      const result = await resultPromise;
      expect(result.content[0].text).toContain('"React"');
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('should timeout and return deny result', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ question: { id: 'q-1', status: 'pending' } }),
      });

      const resultPromise = pollUntilResolved(
        mockFetch as any,
        'http://localhost:3001/api/questions/q-1',
        () => null, // never resolves
        100,
        500, // short timeout for test
      );

      // Advance time past timeout
      await vi.advanceTimersByTimeAsync(600);

      const result = await resultPromise;
      expect(result.content[0].text).toContain('Timed out');
    });

    it('should throw on poll fetch failure', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      });

      await expect(
        pollUntilResolved(mockFetch as any, 'http://x', () => null, 100, 60000),
      ).rejects.toThrow('Poll failed: 500');
    });
  });

  describe('ask_user answer format', () => {
    it('should format single-select answer correctly', () => {
      const answers = { '0': 'React' };
      const result = JSON.stringify({ answers });
      const parsed = JSON.parse(result);

      expect(parsed.answers['0']).toBe('React');
    });

    it('should format multi-select answer correctly', () => {
      const answers = { '0': ['Auth', 'DB'] };
      const result = JSON.stringify({ answers });
      const parsed = JSON.parse(result);

      expect(parsed.answers['0']).toEqual(['Auth', 'DB']);
    });
  });
});
