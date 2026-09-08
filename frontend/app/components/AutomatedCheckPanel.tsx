"use client";

import { useState, useRef, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type PipelineCheck = {
  checked_at: string | null;
  result: string | null;
  months_added: string[];
} | null;

const RESULT_LABELS: Record<string, string> = {
  up_to_date: "Already current, nothing to check",
  no_new_data: "Checked \u2014 no new month published yet",
  success: "New data found and added",
  error_starting_browser: "Failed \u2014 could not start the browser",
  download_ok_clean_failed: "Failed \u2014 downloaded but cleaning failed",
  rebuild_failed: "Failed \u2014 downloaded but warehouse update failed",
};

export default function AutomatedCheckPanel({ initial }: { initial: PipelineCheck }) {
  const [check, setCheck] = useState<PipelineCheck>(initial);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/data-health`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const latest: PipelineCheck = data.last_automated_check ?? null;
        if (latest?.checked_at && latest.checked_at !== startedAtRef.current) {
          setCheck(latest);
          setRunning(false);
          setMessage(null);
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        // transient fetch failure while polling -- just try again next tick
      }
    }, 10000);
  }

  async function triggerCheck() {
    setMessage(null);
    startedAtRef.current = check?.checked_at ?? null;
    try {
      const res = await fetch(`${API_BASE}/api/admin/check-for-updates`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMessage(typeof data.detail === "string" ? data.detail : `Could not start the check (${res.status}).`);
        return;
      }
      if (data.status === "already_running") {
        setMessage("A check is already running \u2014 watching for it to finish.");
        setRunning(true);
        startPolling();
      } else if (data.status === "started") {
        setMessage("Check started \u2014 this can take a few minutes if new data is found.");
        setRunning(true);
        startPolling();
      } else {
        setMessage("Could not start the check.");
      }
    } catch {
      setMessage("Could not reach the API to start the check.");
    }
  }

  return (
    <div>
      {check ? (
        <>
          <p className="health-detail mono">
            Last checked: {check.checked_at ? new Date(check.checked_at).toLocaleString() : "\u2014"}
          </p>
          <p className="health-detail">
            {check.result ? (RESULT_LABELS[check.result] ?? check.result) : "No result recorded yet."}
          </p>
          {check.months_added.length > 0 && (
            <p className="health-detail mono">Added: {check.months_added.join(", ")}</p>
          )}
        </>
      ) : (
        <p className="health-detail">No automated check has run yet.</p>
      )}

      <button
        type="button"
        className="compare-run"
        style={{ marginTop: "1rem" }}
        onClick={triggerCheck}
        disabled={running}
      >
        {running ? "Checking..." : "Check for new data now"}
      </button>

      {message && <p className="page-note" style={{ marginTop: "0.75rem" }}>{message}</p>}

      <p className="page-note" style={{ marginTop: "0.75rem" }}>
        This runs the same script as the scheduled daily check &mdash; a real headless browser
        session against BTS, so it can take a few minutes if new data is actually found. This page
        checks for a result automatically every 10 seconds while a check is running.
      </p>
    </div>
  );
}
