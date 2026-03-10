import React from 'react';
import { RequirementPanel } from '../RequirementPanel';
import { useRequirement } from '../../contexts/RequirementContext';

interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const { planId, isPanelOpen, closePanel } = useRequirement();

  return (
    <div className="flex w-full h-screen overflow-hidden bg-background relative">
      <main className="flex-1 flex flex-col overflow-hidden h-full">
        {children}
      </main>
      {isPanelOpen && planId && (
        <RequirementPanel planId={planId} onClose={closePanel} />
      )}
    </div>
  );
}
