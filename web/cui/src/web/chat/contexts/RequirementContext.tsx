import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface RequirementContextType {
  planId: string | null;
  isPanelOpen: boolean;
  setPlanId: (id: string | null) => void;
  togglePanel: () => void;
  closePanel: () => void;
}

const RequirementContext = createContext<RequirementContextType>({
  planId: null,
  isPanelOpen: false,
  setPlanId: () => {},
  togglePanel: () => {},
  closePanel: () => {},
});

export function RequirementProvider({ children }: { children: ReactNode }) {
  const [planId, setPlanIdState] = useState<string | null>(null);
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  const setPlanId = useCallback((id: string | null) => {
    setPlanIdState(id);
    if (id) {
      setIsPanelOpen(true);
    }
  }, []);

  const togglePanel = useCallback(() => {
    setIsPanelOpen((prev) => !prev);
  }, []);

  const closePanel = useCallback(() => {
    setIsPanelOpen(false);
  }, []);

  return (
    <RequirementContext.Provider
      value={{ planId, isPanelOpen, setPlanId, togglePanel, closePanel }}
    >
      {children}
    </RequirementContext.Provider>
  );
}

export function useRequirement() {
  return useContext(RequirementContext);
}
