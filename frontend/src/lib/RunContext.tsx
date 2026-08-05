import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

interface RunContextValue {
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  lastSource: string;
  setLastSource: (s: string) => void;
}

const RunContext = createContext<RunContextValue | null>(null);

const RUN_KEY = "autoaudit:active-run-id";
const SOURCE_KEY = "autoaudit:last-source";

export function RunProvider({ children }: { children: ReactNode }) {
  const [activeRunId, setActiveRunIdState] = useState<string | null>(() => localStorage.getItem(RUN_KEY));
  const [lastSource, setLastSourceState] = useState<string>(
    () => localStorage.getItem(SOURCE_KEY) ?? ""
  );

  useEffect(() => {
    if (activeRunId) localStorage.setItem(RUN_KEY, activeRunId);
    else localStorage.removeItem(RUN_KEY);
  }, [activeRunId]);

  useEffect(() => {
    localStorage.setItem(SOURCE_KEY, lastSource);
  }, [lastSource]);

  return (
    <RunContext.Provider
      value={{
        activeRunId,
        setActiveRunId: setActiveRunIdState,
        lastSource,
        setLastSource: setLastSourceState,
      }}
    >
      {children}
    </RunContext.Provider>
  );
}

export function useRunContext() {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRunContext must be used within RunProvider");
  return ctx;
}
