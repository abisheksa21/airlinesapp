import Link from "next/link";

type StateProps = {
  title?: string;
  message?: string;
  action?: { href: string; label: string };
};

export function LoadingState({ title = "Preparing the view", message = "Loading a compact, aggregated response from the local warehouse." }: StateProps) {
  return <section className="state-panel state-loading" aria-live="polite"><span className="state-kicker">Loading</span><h2>{title}</h2><p>{message}</p><div className="state-lines" aria-hidden="true"><i /><i /><i /></div></section>;
}

export function ErrorState({ title = "This analysis could not be loaded", message = "The rest of the workspace is still available. Check the local data service and try again.", action }: StateProps) {
  return <section className="state-panel state-error" role="alert"><span className="state-kicker">Unavailable</span><h2>{title}</h2><p>{message}</p>{action && <Link href={action.href} className="text-action">{action.label} →</Link>}</section>;
}

export function EmptyState({ title = "No matching records", message = "Try a wider period or a different aviation object.", action }: StateProps) {
  return <section className="state-panel"><span className="state-kicker">No result</span><h2>{title}</h2><p>{message}</p>{action && <Link href={action.href} className="text-action">{action.label} →</Link>}</section>;
}

export function InsufficientHistoryState({ title = "Not enough history for a dependable read", message = "This result is intentionally withheld rather than turning a small sample into a strong-looking conclusion.", action }: StateProps) {
  return <section className="state-panel state-insufficient"><span className="state-kicker">Evidence boundary</span><h2>{title}</h2><p>{message}</p>{action && <Link href={action.href} className="text-action">{action.label} →</Link>}</section>;
}
