import { useEffect, useState } from "react";
import { decide, getApplication, reverify } from "../api";
import type { AppDetail, Box, Verdict } from "../types";

const V_COLOR: Record<Verdict, string> = {
  pass: "#16a34a", warn: "#d97706", needs_review: "#d97706", fail: "#dc2626",
};

export function ReviewView({ id, onBack }: { id: string; onBack: () => void }) {
  const [app, setApp] = useState<AppDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    getApplication(id).then(setApp).catch((e) => setError(String(e)));
  }, [id]);
  if (error)
    return (
      <div className="space-y-3">
        <button onClick={onBack} className="text-blue-600">← Back to queue</button>
        <p className="text-red-700">Could not load this application: {error}</p>
      </div>
    );
  if (!app) return <p className="text-slate-500">Loading…</p>;
  const v = app.verification;
  const active = v?.fields.find((f) => f.field === hover);

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-blue-600">← Back to queue</button>
        {import.meta.env.DEV && (
          <button
            onClick={() => reverify(id).then(setApp).catch((e) => setError(String(e)))}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
            title="Re-run verification (development only)">
            ↻ Re-run verification (dev)
          </button>
        )}
      </div>
      <h2 className="text-xl font-medium text-slate-800">{app.brand_name}</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-2">
          <LabelImage id={id} highlight={active ? { boxes: active.boxes, verdict: active.verdict } : undefined} />
          <p className="text-xs text-slate-500">Hover a check on the right to highlight it on the label.</p>
        </div>

        <div className="space-y-3">
          {v?.fields.map((f) => (
            <div key={f.field} onMouseEnter={() => setHover(f.field)} onMouseLeave={() => setHover(null)}
              className="cursor-pointer rounded-lg border border-slate-200 bg-white p-3 hover:border-slate-400">
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-800">{f.label}</span>
                <span className="text-sm font-semibold uppercase" style={{ color: V_COLOR[f.verdict] }}>
                  {f.verdict.replaceAll("_", " ")}
                </span>
              </div>
              <p className="text-sm text-slate-600">
                {f.kind === "match" && <>declared <b>{f.expected}</b> · </>}{f.detail}
              </p>
            </div>
          ))}

          <details className="rounded-lg border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              What the reader extracted (OCR) — compare against the label
            </summary>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-600">
              {v?.text || "—"}
            </p>
          </details>

          <div className="flex gap-2 pt-2">
            <button onClick={() => act("approved")} className="rounded-md bg-green-600 px-4 py-2 text-white">Approve</button>
            <button onClick={() => act("needs_correction")} className="rounded-md bg-amber-600 px-4 py-2 text-white">Needs correction</button>
            <button onClick={() => act("rejected")} className="rounded-md bg-red-600 px-4 py-2 text-white">Reject</button>
          </div>
          <p className="text-sm text-slate-500">Status: <b>{app.status.replaceAll("_", " ")}</b></p>
        </div>
      </div>
    </div>
  );
}

function LabelImage({ id, highlight }: { id: string; highlight?: { boxes: Box[]; verdict: Verdict } }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  return (
    <div className="border border-slate-200 bg-white">
      <div className="relative">
        <img src={`/api/applications/${id}/image`} alt="submitted label" className="block w-full"
          onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
        {dim && highlight && highlight.boxes.length > 0 && (
          // viewBox = natural pixels, preserveAspectRatio=none stretches it to exactly cover the
          // displayed <img>, so boxes stay aligned at any size; non-scaling-stroke keeps lines crisp.
          <svg viewBox={`0 0 ${dim.w} ${dim.h}`} preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 h-full w-full">
            {highlight.boxes.map((b, i) => (
              <rect key={i} x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]}
                fill={V_COLOR[highlight.verdict]} fillOpacity={0.15}
                stroke={V_COLOR[highlight.verdict]} strokeWidth={2} vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
