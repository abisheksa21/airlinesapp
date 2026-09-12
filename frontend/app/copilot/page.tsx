"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { useMode } from "../lib/mode";
import DistanceBucketChart from "../components/DistanceBucketChart";
import CodeshareChart from "../components/CodeshareChart";
import DelayPropagationSummary from "../components/DelayPropagationSummary";
import TimeOfDayChart from "../components/TimeOfDayChart";
import CancellationCauseChart from "../components/CancellationCauseChart";
import HealthBadge from "../components/HealthBadge";
import TurnbackSummary from "../components/TurnbackSummary";
import DiversionLandingChart from "../components/DiversionLandingChart";
import SchedulePaddingChart from "../components/SchedulePaddingChart";
import FlexibleQueryChart from "../components/FlexibleQueryChart";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8200";

type ToolEvidence = { tool: string; result: any };

type Message = {
  role: "user" | "assistant";
  content: string;
  toolUsed?: string[] | null;
  evidence?: ToolEvidence[] | null;
  error?: boolean;
  streaming?: boolean;
  activeTools?: string[];
};

const SUGGESTIONS = [
  "Which carrier has the best on-time rate?",
  "Does flight distance affect delays?",
  "If my inbound plane is late will my connection be late too?",
  "Does Delta codeshare?",
];

type Conversation = {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
};

const STORAGE_KEY = "copilot_conversations_v1";

// Client-side only (no user accounts on this site), so past chats live in
// this browser only -- not synced across devices, cleared if the user
// clears site data. Good enough for "let me revisit what I asked
// yesterday," not a substitute for a real account-backed history.
function loadConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveConversations(conversations: Conversation[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  } catch {
    // Storage unavailable or quota exceeded -- chat still works for this
    // session, it just won't persist. Not worth surfacing as an error.
  }
}

function titleFromMessages(messages: Message[]): string {
  const firstUser = messages.find((m) => m.role === "user");
  const text = firstUser?.content.trim() ?? "";
  if (!text) return "New chat";
  return text.length > 48 ? `${text.slice(0, 48)}...` : text;
}

function newConversationId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// Maps a tool name to a renderer for its evidence -- reuses the exact same
// chart components used elsewhere on the site, not a separate chat-only
// visual language. Returns null (renders nothing) for tools with no
// chart-compatible shape yet, or a failed/empty tool result.
const EVIDENCE_RENDERERS: Record<string, (result: any) => React.ReactNode> = {
  get_distance_buckets: (result) =>
    result?.buckets?.length ? <DistanceBucketChart data={result.buckets} /> : null,
  get_codeshare: (result) =>
    result?.groups?.length ? <CodeshareChart data={result.groups} /> : null,
  get_delay_propagation: (result) =>
    result && !result.error ? <DelayPropagationSummary data={result} /> : null,
  get_time_of_day: (result) =>
    result?.hours?.length ? <TimeOfDayChart data={result.hours} /> : null,
  get_cancellation_causes: (result) =>
    result?.causes?.length ? <CancellationCauseChart data={result.causes} /> : null,
  get_health_score: (result) =>
    result && !result.error ? <HealthBadge health={result} /> : null,
  get_turnbacks: (result) =>
    result && !result.error ? <TurnbackSummary data={result} /> : null,
  get_diversions: (result) =>
    result?.landing_buckets?.length ? <DiversionLandingChart data={result.landing_buckets} /> : null,
  get_schedule_padding: (result) =>
    result?.periods?.length ? <SchedulePaddingChart data={result.periods} /> : null,
  flexible_query: (result) =>
    result?.groups?.length ? <FlexibleQueryChart groups={result.groups} /> : null,
};

function toolLabel(tool: string): string {
  return `${tool}()`;
}

export default function CopilotPage() {
  const { mode } = useMode();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  // Source of truth for which conversation a background write targets --
  // a ref (not state) so the persistence effect below always writes to the
  // right id even if it fires before a state update from "New chat" or
  // "open a past conversation" has re-rendered.
  const activeIdRef = useRef<string>("");

  useEffect(() => {
    const loaded = loadConversations().sort((a, b) => b.updatedAt - a.updatedAt);
    setConversations(loaded);
    if (loaded.length > 0) {
      activeIdRef.current = loaded[0].id;
      setActiveId(loaded[0].id);
      setMessages(loaded[0].messages);
    } else {
      activeIdRef.current = newConversationId();
      setActiveId(activeIdRef.current);
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Persist after every completed exchange (skipped while a message is
  // still streaming, so we're not writing partial/incomplete text).
  useEffect(() => {
    if (messages.length === 0 || loading) return;
    const id = activeIdRef.current;
    setConversations((prev) => {
      const existing = prev.find((c) => c.id === id);
      const updated: Conversation = {
        id,
        title: existing?.title ?? titleFromMessages(messages),
        messages,
        updatedAt: Date.now(),
      };
      const next = existing
        ? prev.map((c) => (c.id === id ? updated : c))
        : [updated, ...prev];
      next.sort((a, b) => b.updatedAt - a.updatedAt);
      saveConversations(next);
      return next;
    });
  }, [messages, loading]);

  function startNewChat() {
    activeIdRef.current = newConversationId();
    setActiveId(activeIdRef.current);
    setMessages([]);
  }

  function openConversation(conv: Conversation) {
    if (loading) return;
    activeIdRef.current = conv.id;
    setActiveId(conv.id);
    setMessages(conv.messages);
  }

  function deleteConversation(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== id);
      saveConversations(next);
      return next;
    });
    if (activeIdRef.current === id) {
      startNewChat();
    }
  }

  function updateLastMessage(update: (last: Message) => Message) {
    setMessages((m) => {
      if (m.length === 0) return m;
      const copy = [...m];
      copy[copy.length - 1] = update(copy[copy.length - 1]);
      return copy;
    });
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || loading) return;

    // Prior turns as Claude-shaped messages, so a follow-up like "compare
    // that with Delta" has the actual conversation to refer to. Only text
    // is preserved, not prior tool_use/tool_result blocks, so a follow-up
    // still triggers fresh tool calls rather than reusing earlier evidence
    // -- a deliberate scope cut, not an oversight. Simpler than the earlier
    // Gemini version needed: Claude's roles ("user"/"assistant") already
    // match this app's own Message.role, no translation required.
    const history = messages
      .filter((m) => m.content && !m.error)
      .map((m) => ({
        role: m.role,
        content: m.content,
      }));

    setMessages((m) => [...m, { role: "user", content: message }]);
    setInput("");
    setLoading(true);
    setMessages((m) => [...m, { role: "assistant", content: "", streaming: true, activeTools: [] }]);

    const toolEvidence: ToolEvidence[] = [];

    try {
      const res = await fetch(`${API_BASE}/api/copilot/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history, tier: mode }),
      });

      if (!res.ok || !res.body) {
        let detail = "Something went wrong.";
        try {
          const data = await res.json();
          detail = data.detail ?? detail;
        } catch {
          // response wasn't JSON -- keep the generic message
        }
        updateLastMessage(() => ({ role: "assistant", content: detail, error: true }));
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let settled = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";

        for (const chunk of chunks) {
          const line = chunk.trim();
          if (!line.startsWith("data:")) continue;
          let event: any;
          try {
            event = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }

          if (event.stage === "tool_start") {
            updateLastMessage((last) => ({
              ...last,
              activeTools: [...(last.activeTools ?? []), event.tool],
            }));
          } else if (event.stage === "tool_complete") {
            toolEvidence.push({ tool: event.tool, result: event.result });
          } else if (event.stage === "answer_chunk") {
            updateLastMessage((last) => ({ ...last, content: (last.content ?? "") + event.text }));
          } else if (event.stage === "done") {
            settled = true;
            updateLastMessage((last) => ({
              role: "assistant",
              content: event.reply || last.content,
              toolUsed: event.tool_used,
              evidence: toolEvidence.length > 0 ? toolEvidence : null,
              streaming: false,
            }));
          } else if (event.stage === "error") {
            settled = true;
            updateLastMessage(() => ({
              role: "assistant",
              content: event.message || "Something went wrong.",
              error: true,
              streaming: false,
            }));
          }
        }
      }

      // The connection can close without ever sending a "done" or "error"
      // event (a dropped connection, a server crash mid-stream) -- without
      // this, the bubble would stay stuck showing "streaming" forever with
      // no explanation.
      if (!settled) {
        updateLastMessage((last) => ({
          role: "assistant",
          content: last.content || "The connection ended before a full response arrived.",
          error: !last.content,
          streaming: false,
          evidence: toolEvidence.length > 0 ? toolEvidence : null,
        }));
      }
    } catch {
      updateLastMessage(() => ({ role: "assistant", content: "Could not reach the API.", error: true }));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page copilot-page">
      <header className="header">
        <p className="eyebrow">DOT On-Time Performance &middot; Copilot</p>
        <h1 className="title">Ask the data</h1>
        <p className="subtitle">
          Grounded in the same 60M-flight warehouse as the stats page &mdash; every answer comes from a real query, not a guess.
        </p>
        <p className="page-note" style={{ marginTop: "0.4rem" }}>
          Running in {mode === "researcher" ? "Researcher mode" : "Public mode"} &mdash; switch in the
          nav bar for a {mode === "researcher" ? "faster, lighter" : "deeper, more capable"} model.
        </p>
      </header>

      <div className="copilot-layout">
        <aside className="copilot-sidebar">
          <button className="copilot-new-chat" onClick={startNewChat}>
            + New chat
          </button>
          <div className="copilot-conversation-list">
            {conversations.length === 0 && (
              <p className="page-note" style={{ padding: "0.5rem" }}>
                Past chats will show up here &mdash; saved in this browser only.
              </p>
            )}
            {conversations.map((conv) => (
              <div
                key={conv.id}
                className={`copilot-conversation-item ${conv.id === activeId ? "active" : ""}`}
                onClick={() => openConversation(conv)}
              >
                <span className="copilot-conversation-title">{conv.title}</span>
                <button
                  className="copilot-conversation-delete"
                  onClick={(e) => deleteConversation(conv.id, e)}
                  aria-label="Delete conversation"
                  title="Delete conversation"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>
        </aside>

        <div className="copilot-main">
          <div className="chat-window">
            {messages.length === 0 && (
              <div className="chat-empty">
                <p className="eyebrow" style={{ marginBottom: "0.75rem" }}>Try asking</p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="suggestion-chip" onClick={() => send(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
          <div key={i} className={`bubble bubble-${m.role} ${m.error ? "bubble-error" : ""}`}>
            {m.streaming && !m.content && m.activeTools && m.activeTools.length > 0 && (
              <p className="bubble-tool mono" style={{ marginBottom: "0.5rem" }}>
                Running {toolLabel(m.activeTools[m.activeTools.length - 1])}...
              </p>
            )}
            {m.streaming && !m.content && (!m.activeTools || m.activeTools.length === 0) && (
              <div className="bubble-loading" style={{ padding: 0 }}>
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </div>
            )}
            <div className="bubble-content">
              <ReactMarkdown>{m.content}</ReactMarkdown>
              {m.streaming && m.content && <span className="cursor-blink">&#9612;</span>}
            </div>
            {m.evidence && m.evidence.length > 0 && (
              <div className="bubble-evidence">
                {m.evidence.map((e, j) => {
                  const renderer = EVIDENCE_RENDERERS[e.tool];
                  const node = renderer ? renderer(e.result) : null;
                  return node ? <div key={j} style={{ marginTop: "1rem" }}>{node}</div> : null;
                })}
              </div>
            )}
            {m.toolUsed && m.toolUsed.length > 0 && (
              <p className="bubble-tool mono">
                via {m.toolUsed.map(toolLabel).join(", ")}
              </p>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
          </div>

          <form
            className="chat-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about carriers, delays, trends..."
              disabled={loading}
            />
            <button className="chat-send" type="submit" disabled={loading || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      </div>
    </main>
  );
}

