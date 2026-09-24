"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type QuickMessage = { role: "user" | "assistant"; content: string; error?: boolean; streaming?: boolean; status?: string };

export function CopilotLauncher({ mode }: { mode: "public" | "researcher" }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<QuickMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent | globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [messages]);

  if (mode === "researcher") {
    if (pathname === "/research/copilot") return null;
    return <Link className="copilot-launcher copilot-launcher-researcher" href="/research/copilot" aria-label="Open persistent Research Copilot">
      <span className="copilot-launcher-mark" aria-hidden="true">✦</span><span>Research Copilot</span><span className="copilot-launcher-hint">↗</span>
    </Link>;
  }

  // The full public chat is its own page. The floating quick chat remains
  // mounted in the public shell, so its in-memory thread survives navigation
  // but is naturally discarded by a hard refresh.
  if (pathname === "/copilot") return null;

  function updateLast(update: (message: QuickMessage) => QuickMessage) {
    setMessages((current) => current.map((message, index) => index === current.length - 1 ? update(message) : message));
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || loading) return;
    const history = messages.filter((message) => message.content && !message.error).map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, { role: "user", content: question }, { role: "assistant", content: "", streaming: true, status: "Checking the historical flight record…" }]);
    setInput("");
    setLoading(true);
    let settled = false;
    try {
      const response = await fetch(`${API_BASE}/api/copilot/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, history, tier: "public" }),
      });
      if (!response.ok || !response.body) {
        let detail = "Copilot could not answer that just now.";
        try { detail = (await response.json()).detail ?? detail; } catch { /* Keep the fallback message. */ }
        updateLast((message) => ({ ...message, content: detail, error: true, streaming: false, status: undefined }));
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split(/\r?\n\r?\n/);
        buffer = events.pop() ?? "";
        for (const block of events) {
          const dataLine = block.split(/\r?\n/).find((line) => line.startsWith("data:"));
          if (!dataLine) continue;
          let event: { stage?: string; text?: string; reply?: string; message?: string; tool?: string };
          try { event = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
          if (event.stage === "tool_start") {
            updateLast((message) => ({ ...message, status: `Looking up ${event.tool?.replaceAll("_", " ") ?? "historical evidence"}…` }));
          } else if (event.stage === "answer_chunk") {
            updateLast((message) => ({ ...message, content: `${message.content}${event.text ?? ""}`, status: undefined }));
          } else if (event.stage === "done") {
            settled = true;
            updateLast((message) => ({ ...message, content: event.reply || message.content, streaming: false, status: undefined }));
          } else if (event.stage === "error") {
            settled = true;
            updateLast((message) => ({ ...message, content: event.message || "Copilot could not complete the answer.", error: true, streaming: false, status: undefined }));
          }
        }
      }
      if (!settled) updateLast((message) => ({ ...message, content: message.content || "The connection ended before a complete answer arrived.", error: !message.content, streaming: false, status: undefined }));
    } catch {
      updateLast((message) => ({ ...message, content: "Could not reach the data service. Check that the backend is running.", error: true, streaming: false, status: undefined }));
    } finally {
      setLoading(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(input);
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(input);
    }
  }

  return <div className="public-quick-copilot">
    {open && <section className="quick-copilot-panel" role="dialog" aria-label="Temporary public Copilot chat">
      <header className="quick-copilot-header">
        <div><span className="copilot-launcher-mark" aria-hidden="true">✦</span><div><strong>Ask Copilot</strong><small>Quick answer · Haiku</small></div></div>
        <div className="quick-copilot-actions">
          <Link href="/copilot" className="quick-copilot-full-link" onClick={() => setOpen(false)}>History ↗</Link>
          <button type="button" onClick={() => { if (!loading) setMessages([]); }} disabled={loading || messages.length === 0} aria-label="Start a new temporary chat" title="Clear this quick session">New</button>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close quick Copilot">×</button>
        </div>
      </header>
      <div className="quick-copilot-session-note">Temporary session · clears when you reload</div>
      <div className="quick-copilot-messages" aria-live="polite">
        {messages.length === 0 && <div className="quick-copilot-welcome"><strong>What would you like to know?</strong><p>Ask a quick question about historical flights, airlines, airports, or routes.</p><Link href="/copilot" onClick={() => setOpen(false)}>Open full Copilot with saved chat history ↗</Link></div>}
        {messages.map((message, index) => <article key={`${index}-${message.role}`} className={`quick-copilot-message ${message.role}${message.error ? " error" : ""}`}>
          <span>{message.role === "user" ? "You" : "Copilot"}</span>
          {message.status && <small>{message.status}</small>}
          {message.content && <p>{message.content}</p>}
          {message.streaming && !message.content && !message.status && <small>Preparing an answer…</small>}
        </article>)}
        <div ref={bottomRef} />
      </div>
      <form className="quick-copilot-form" onSubmit={submit}>
        <textarea ref={inputRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={handleInputKeyDown} placeholder="Ask about the flight record…" rows={2} disabled={loading} aria-label="Your question for public Copilot" />
        <button type="submit" disabled={loading || !input.trim()}>{loading ? "…" : "Send"}</button>
      </form>
    </section>}
    <button type="button" className="copilot-launcher copilot-launcher-public" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-label={open ? "Close temporary Ask Copilot panel" : "Ask Copilot for a temporary answer"}>
      <span className="copilot-launcher-mark" aria-hidden="true">✦</span><span>{open ? "Close" : "Ask Copilot"}</span><span className="copilot-launcher-hint">{open ? "×" : "⌄"}</span>
    </button>
  </div>;
}
