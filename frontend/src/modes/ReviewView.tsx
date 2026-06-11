import { useEffect, useState } from "react";
import { decide, getApplication } from "../api";
import type { AppDetail, Verdict } from "../types";

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

  async function act(decision: string) {
    setApp(await decide(id, decision, ""));
  }

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-blue-600">← Back to queue</button>
      <h2 className="text-xl font-medium text-slate-800">{app.brand_name}</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <LabelImage id={id} words={v?.words ?? []}
          highlight={v?.fields.find((f) => f.field === hover)} />
        <div className="space-y-3">
          {v?.fields.map((f) => (
            <div key={f.field} onMouseEnter={() => setHover(f.field)} onMouseLeave={() => setHover(null)}
              className="rounded-lg border border-slate-200 bg-white p-3">
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

function LabelImage({ id, words, highlight }:
  { id: string; words: { bbox: [number, number, number, number] }[];
    highlight?: { boxes: [number, number, number, number][]; verdict: Verdict } }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  const src = `/api/applications/${id}/image`;
  return (
    <div className="relative inline-block border border-slate-200 bg-white">
      <img src={src} alt="submitted label" className="block max-w-full"
        onLoad={(e) => setDim({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
      {dim && (
        <svg viewBox={`0 0 ${dim.w} ${dim.h}`} className="absolute inset-0 h-full w-full">
          {words.map((w, i) => (
            <rect key={i} x={w.bbox[0]} y={w.bbox[1]} width={w.bbox[2] - w.bbox[0]}
              height={w.bbox[3] - w.bbox[1]} fill="none" stroke="#94a3b8" strokeWidth={1} opacity={0.4} />
          ))}
          {highlight?.boxes.map((b, i) => (
            <rect key={`h${i}`} x={b[0]} y={b[1]} width={b[2] - b[0]} height={b[3] - b[1]}
              fill="none" stroke={V_COLOR[highlight.verdict]} strokeWidth={3} />
          ))}
        </svg>
      )}
    </div>
  );
}
