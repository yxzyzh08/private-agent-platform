import React, { useRef, useCallback } from 'react';
import { RequirementPanel } from '../RequirementPanel';
import { useRequirement } from '../../contexts/RequirementContext';
import { useIsMobile } from '../../hooks/useIsMobile';

interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const { planId, isPanelOpen, closePanel } = useRequirement();
  const isMobile = useIsMobile();
  const touchStartY = useRef(0);

  const showPanel = isPanelOpen && planId;

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const deltaY = e.changedTouches[0].clientY - touchStartY.current;
    if (deltaY > 100) {
      closePanel();
    }
  }, [closePanel]);

  return (
    <div className="flex w-full h-dvh overflow-hidden bg-background relative">
      <main className="flex-1 flex flex-col overflow-hidden h-full">
        {children}
      </main>
      {showPanel && isMobile && (
        <div className="fixed inset-0 z-50 flex flex-col">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={closePanel}
          />
          <div
            className="relative flex-1 flex flex-col bg-background mt-8 rounded-t-2xl overflow-hidden animate-in slide-in-from-bottom duration-300"
            onTouchStart={handleTouchStart}
            onTouchEnd={handleTouchEnd}
          >
            <div className="flex justify-center py-2">
              <div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
            </div>
            <RequirementPanel planId={planId} onClose={closePanel} />
          </div>
        </div>
      )}
      {showPanel && !isMobile && (
        <RequirementPanel planId={planId} onClose={closePanel} />
      )}
    </div>
  );
}
