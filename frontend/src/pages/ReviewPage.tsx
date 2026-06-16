import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { decide, getApplication, reverify } from "../api";
import type { AppDetail } from "../types";
import { VerificationView } from "../VerificationView";
import { StatusBadge, VERDICT, btnFail, btnPass } from "../ui";

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
        <Link to="/queue" className="text-sm font-medium text-brand hover:underline">← Review queue</Link>
        <p role="alert" className="text-fail">Could not load this application: {error}</p>
      </div>
    );
  if (!app) return <p className="text-muted">Loading review…</p>;
  const v = app.verification;

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

  const actions = (
    <div className="space-y-2 border-t border-line pt-4">
      <div className="flex flex-wrap gap-2.5">
        <button onClick={() => act("approved")} className={`${btnPass} px-5 py-2.5 text-sm`}>Approve</button>
        <button onClick={() => act("rejected")} className={`${btnFail} px-5 py-2.5 text-sm`}>Reject</button>
      </div>
      <p className="text-sm text-muted">The tool assists — the agent decides.</p>
    </div>
  );

  return (
    <div className="rise space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/queue" className="inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">
          <span aria-hidden>←</span> Review queue
        </Link>
        {import.meta.env.DEV && (
          <button
            onClick={() => reverify(id).then(setApp).catch((e) => setError(String(e)))}
            className="rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-muted transition hover:border-line-strong hover:bg-surface"
            title="Re-run verification (development only)">
            ↻ Re-run (dev)
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-[1.9rem] font-semibold leading-tight tracking-tight text-ink">{app.brand_name}</h1>
          <p className="mt-1 text-muted">{app.class_type} · {app.alcohol_content} · {app.net_contents}</p>
        </div>
        <div className="flex items-center gap-2">
          {v && (
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold uppercase tracking-wide ring-1 ring-inset ${VERDICT[v.overall].cls}`}>
              <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${VERDICT[v.overall].dot}`} />
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
