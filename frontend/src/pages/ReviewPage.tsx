import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { decide, getApplication, reverify } from "../api";
import type { AppDetail, Box, Verdict } from "../types";
import { StatusBadge, VERDICT, VerdictPill } from "../ui";

export function ReviewPage() {
  const { id = "" } = useParams();
  const [app, setApp] = useState<AppDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

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
  const active = v?.fields.find((f) => f.field === hover);

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

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

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-2">
          <LabelImage id={id} highlight={active ? { boxes: active.boxes, verdict: active.verdict } : undefined} />
          <p className="text-xs text-muted">Hover a check to highlight its region on the label.</p>
        </div>

        <div className="space-y-3">
          {v?.fields.map((f) => (
            <div
              key={f.field}
              onMouseEnter={() => setHover(f.field)}
              onMouseLeave={() => setHover(null)}
              className="cursor-pointer rounded-lg border border-line bg-surface p-3 transition hover:border-brand/40 hover:shadow-sm"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-ink">{f.label}</span>
                <VerdictPill verdict={f.verdict} />
              </div>
              <p className="mt-0.5 text-sm text-muted">
                {f.kind === "match" && <>declared <b className="text-ink">{f.expected}</b> · </>}{f.detail}
              </p>
            </div>
          ))}

          <details className="rounded-lg border border-line bg-surface p-3">
            <summary className="cursor-pointer text-sm font-medium text-ink">
              What the reader extracted (OCR)
            </summary>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm text-muted">{v?.text || "—"}</p>
            {v && <p className="mt-2 text-xs text-muted">Read by {v.engine} in {Math.round(v.elapsed_ms)} ms.</p>}
          </details>

          <div className="flex flex-wrap gap-2 pt-1">
            <button onClick={() => act("approved")} className="rounded-md bg-pass px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110">Approve</button>
            <button onClick={() => act("needs_correction")} className="rounded-md bg-flag px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110">Needs correction</button>
            <button onClick={() => act("rejected")} className="rounded-md bg-fail px-4 py-2.5 text-sm font-semibold text-white transition hover:brightness-110">Reject</button>
          </div>
          <p className="text-sm text-muted">The tool assists — the agent decides.</p>
        </div>
      </div>
    </div>
  );
}

function LabelImage({ id, highlight }: { id: string; highlight?: { boxes: Box[]; verdict: Verdict } }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-sm">
      <div className="relative">
        <img
          src={`/api/applications/${id}/image`}
          alt="submitted label"
          className="block w-full"
          onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
        {dim && highlight && highlight.boxes.length > 0 && (
          <svg
            viewBox={`0 0 ${dim.w} ${dim.h}`}
            preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 h-full w-full"
          >
            {highlight.boxes.map((b, i) => (
              <rect
                key={i}
                x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]}
                fill={VERDICT[highlight.verdict].hex} fillOpacity={0.14}
                stroke={VERDICT[highlight.verdict].hex} strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
