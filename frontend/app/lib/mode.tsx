"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type SiteMode = "public" | "researcher";

const STORAGE_KEY = "site_mode_v1";

type ModeContextValue = {
  mode: SiteMode;
  setMode: (mode: SiteMode) => void;
};

const ModeContext = createContext<ModeContextValue>({
  mode: "public",
  setMode: () => {},
});

export function ModeProvider({ children }: { children: React.ReactNode }) {
  // Starts "public" on every render (including the server-rendered first
  // pass) and only switches to a stored "researcher" choice after mount --
  // avoids a server/client mismatch, at the cost of a one-frame flash back
  // to public mode on reload for someone who'd picked researcher. Cheap
  // trade for a feature this size.
  const [mode, setModeState] = useState<SiteMode>("public");

  useEffect(() => {
    document.documentElement.dataset.siteMode = mode;
  }, [mode]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "researcher" || stored === "public") {
        setModeState(stored);
      }
    } catch {
      // localStorage unavailable -- just stay on the default
    }
  }, []);

  function setMode(next: SiteMode) {
    setModeState(next);
    document.documentElement.dataset.siteMode = next;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // storage failure isn't worth surfacing here -- mode still works
      // for the current session, just won't persist
    }
  }

  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export function useMode() {
  return useContext(ModeContext);
}
