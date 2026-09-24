"use client";

import { useCallback, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

export type SiteMode = "public" | "researcher";

export function ModeProvider({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function useMode() {
  const pathname = usePathname();
  const router = useRouter();
  const mode: SiteMode = pathname.startsWith("/research") || ["/aircraft", "/capacity", "/compare", "/data-health", "/decision-center", "/delays", "/max-grounding", "/model-evidence"].some((path) => pathname === path || pathname.startsWith(`${path}/`)) ? "researcher" : "public";
  useEffect(() => { document.documentElement.dataset.siteMode = mode; }, [mode]);
  const setMode = useCallback((next: SiteMode) => { router.push(next === "researcher" ? "/research" : "/"); }, [router]);
  return { mode, setMode };
}
