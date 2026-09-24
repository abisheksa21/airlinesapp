"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";
type SavedInvestigation = { id: string; href: string; label: string; saved_at: string };

export function SavedInvestigationMenu() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<SavedInvestigation[]>([]);
  const [status, setStatus] = useState("");
  const [working, setWorking] = useState(false);
  const href = useMemo(() => `${pathname}${searchParams.size ? `?${searchParams.toString()}` : ""}`, [pathname, searchParams]);

  const loadSaved = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/investigations`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Saved investigations are unavailable.");
      setSaved(payload.investigations ?? []);
      setStatus("");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Saved investigations are unavailable.");
    }
  }, []);

  useEffect(() => { if (open) void loadSaved(); }, [loadSaved, open]);

  async function saveCurrent() {
    const label = `${pathname.replace("/research", "Research").replaceAll("-", " ")} ${searchParams.size ? "· scoped" : ""}`.trim();
    setWorking(true);
    try {
      const response = await fetch(`${API_BASE}/api/investigations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ href, label }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not save this investigation.");
      await loadSaved();
      setStatus("Saved to this local app instance.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not save this investigation.");
    } finally {
      setWorking(false);
    }
  }

  async function remove(investigationId: string) {
    setWorking(true);
    try {
      const response = await fetch(`${API_BASE}/api/investigations/${encodeURIComponent(investigationId)}`, { method: "DELETE" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Could not remove this investigation.");
      setSaved((current) => current.filter((item) => item.id !== investigationId));
      setStatus("Saved investigation removed.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not remove this investigation.");
    } finally {
      setWorking(false);
    }
  }

  async function copyLink() {
    try { await navigator.clipboard.writeText(window.location.href); } catch { /* Clipboard permissions vary by browser. */ }
  }

  return <div className="saved-investigations"><button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-label="Save or open an investigation" title="Save or open investigation">⌑ <span>Saved</span></button>{open && <section className="saved-investigations-popover" aria-label="Saved investigations"><div><span className="section-label">Investigation links</span><button type="button" onClick={() => setOpen(false)} aria-label="Close saved investigations">×</button></div><p>Saved links live in this local application instance, not in your browser storage or Git.</p><div className="saved-actions"><button type="button" onClick={() => void saveCurrent()} disabled={working}>{working ? "Saving…" : "Save this view"}</button><button type="button" onClick={() => void copyLink()}>Copy link</button></div>{status && <p className="saved-status" role="status">{status}</p>}{saved.length ? <ul>{saved.map((item) => <li key={item.id}><Link href={item.href} onClick={() => setOpen(false)}><strong>{item.label}</strong><small>{item.href}</small></Link><button type="button" onClick={() => void remove(item.id)} disabled={working} aria-label={`Remove ${item.label}`}>×</button></li>)}</ul> : <p className="saved-empty">No saved investigations yet.</p>}</section>}</div>;
}
