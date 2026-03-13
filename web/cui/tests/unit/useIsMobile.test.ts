/**
 * @vitest-environment happy-dom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useIsMobile } from '@/web/chat/hooks/useIsMobile';

describe('useIsMobile', () => {
  let changeHandlers: Array<(e: MediaQueryListEvent) => void>;
  let matchesValue: boolean;
  let removeSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    changeHandlers = [];
    matchesValue = false;
    removeSpy = vi.fn();

    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: matchesValue,
      media: query,
      addEventListener: vi.fn((event: string, handler: (e: MediaQueryListEvent) => void) => {
        if (event === 'change') changeHandlers.push(handler);
      }),
      removeEventListener: removeSpy,
    })));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should return false on desktop (> 768px)', () => {
    matchesValue = false;
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  it('should return true on mobile (<= 768px)', () => {
    matchesValue = true;
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('should update when media query changes', () => {
    matchesValue = false;
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      changeHandlers.forEach(h => h({ matches: true } as MediaQueryListEvent));
    });

    expect(result.current).toBe(true);
  });

  it('should clean up listener on unmount', () => {
    const { unmount } = renderHook(() => useIsMobile());
    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 768px)');

    unmount();
    expect(removeSpy).toHaveBeenCalledWith('change', expect.any(Function));
  });
});
