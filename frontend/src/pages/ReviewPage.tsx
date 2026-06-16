import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { decide, getApplication, reverify } from "../api";
import type { AppDetail } from "../types";
import { VerificationView } from "../VerificationView";
import { StatusBadge, VERDICT } from "../ui";

export function ReviewPage() {
  const { id = "" } = useParams();
  const [app, setApp] = useState<AppDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setApp(null);
    setError(null);
    getApplication(id).then(setApp).catch((e) => setError(String(e)));
  }, [id]);

  if (error)
    return (
      <div className="space-y-3">
        <Link to="/queue" className="text-sm text-brand hover:underline">← Review queue</Link>
        <p className="text-fail">Could not load this application: {error}</p>
      </div>
    );
  if (!app) return <p className="text-muted">Loading review…</p>;
  const v = app.verification;

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

  const actions = (
    <>
      <div className="flex flex-wrap gap-2 pt-1">
        <button onClick={() => act("approved")} className="rounded-md bg-pass px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110">Approve</button>
        <button onClick={() => act("rejected")} className="rounded-md bg-fail px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110">Reject</button>
      </div>
      <p className="text-sm text-muted">The tool assists — the agent decides.</p>
    </>
  );

  return (
    <div className="rise space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/queue" className="text-sm text-brand hover:underline">← Review queue</Link>
        {import.meta.env.DEV && (
          <button
            onClick={() => reverify(id).then(setApp).catch((e) => setError(String(e)))}
            className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-surface"
            title="Re-run verification (development only)">
            ↻ Re-run (dev)
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-2xl font-semibold text-ink">{app.brand_name}</h1>
          <p className="text-muted">{app.class_type} · {app.alcohol_content} · {app.net_contents}</p>
        </div>
        <div className="flex items-center gap-2">
          {v && (
            <span className={`rounded-full px-3 py-1 text-sm font-bold uppercase tracking-wide ${VERDICT[v.overall].cls}`}>
              {VERDICT[v.overall].label}
            </span>
          )}
          <StatusBadge status={app.status} />
        </div>
      </div>

      <VerificationView
        verification={app.verification}
        imageSrc={`/api/applications/${app.id}/image`}
        actions={actions}
      />
    </div>
  );
}
