import { type ReactNode, useCallback, useState } from "react";
import type { Box, Verdict, Verification } from "./types";
import { VERDICT, VerdictPill } from "./ui";

/** Shared result view: the label with hover-highlighted regions on the left, and a
 *  per-field breakdown (declared vs. found, right under each check) on the right.
 *  Reused by the agent review (persisted image URL + Approve/Reject) and the submit-time
 *  self-check (local object URL + Submit-as-is/Adjust) — only `imageSrc` and `actions` differ. */
export function VerificationView({
  verification: v,
  imageSrc,
  actions,
}: {
  verification: Verification | null;
  imageSrc: string;
  actions?: ReactNode;
}) {
  const [hover, setHover] = useState<string | null>(null);
  if (!v) return <p className="text-muted">No verification available.</p>;
  const active = v.fields.find((f) => f.field === hover);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-2 lg:sticky lg:top-20 lg:self-start">
        <LabelImage
          src={imageSrc}
          highlight={active ? { boxes: active.boxes, verdict: active.verdict } : undefined}
        />
        <p className="text-xs text-muted">Hover a check to highlight its region on the label.</p>
      </div>

      <div className="space-y-2.5">
        {v.fields.map((f) => (
          <div
            key={f.field}
            onMouseEnter={() => setHover(f.field)}
            onMouseLeave={() => setHover(null)}
            className="cursor-pointer rounded-xl border border-line bg-surface p-3.5 shadow-sm transition hover:border-brand/40 hover:shadow-card"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-ink">{f.label}</span>
              <VerdictPill verdict={f.verdict} />
            </div>

            {f.kind === "match" ? (
              <dl className="mt-2.5 grid grid-cols-[5rem_1fr] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-muted">Declared</dt>
                <dd className="text-ink">{f.expected || "—"}</dd>
                <dt className="text-muted">Found</dt>
                <dd>
                  <code className="rounded bg-paper px-1.5 py-0.5 font-mono text-xs text-ink ring-1 ring-inset ring-line">
                    {f.found || "— not detected on label"}
                  </code>
                </dd>
              </dl>
            ) : (
              f.found && (
                <p className="mt-2.5 text-sm">
                  <span className="text-muted">Found </span>
                  <code className="rounded bg-paper px-1.5 py-0.5 font-mono text-xs text-ink ring-1 ring-inset ring-line">{f.found}</code>
                </p>
              )
            )}

            <p className="mt-2 text-xs leading-relaxed text-muted">{f.detail}</p>
          </div>
        ))}

        <details className="rounded-xl border border-line bg-surface p-3.5">
          <summary className="cursor-pointer text-sm font-semibold text-ink">
            Full reader output (raw OCR)
          </summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-muted">{v.text || "—"}</p>
          <p className="mt-2 text-xs text-muted">Read by {v.engine} in {Math.round(v.elapsed_ms)} ms.</p>
        </details>

        {v.warning_tier === 2 ? (
          <p className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-xs font-medium text-brand">
            <span aria-hidden>✦</span> Read with model assistance (Tier 2)
          </p>
        ) : null}

        {actions}
      </div>
    </div>
  );
}

function LabelImage({ src, highlight }: { src: string; highlight?: { boxes: Box[]; verdict: Verdict } }) {
  const [dim, setDim] = useState<{ w: number; h: number } | null>(null);
  // Callback ref: read natural dimensions reliably whether the image is already cached
  // (complete on attach) or still loading (set on the load event). Avoids the React
  // onLoad timing gap that can leave the overlay without dimensions.
  const imgRef = useCallback((img: HTMLImageElement | null) => {
    if (!img) return;
    const read = () => img.naturalWidth && setDim({ w: img.naturalWidth, h: img.naturalHeight });
    if (img.complete) read();
    else img.addEventListener("load", read, { once: true });
  }, []);
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface p-3 shadow-card">
      <div className="relative overflow-hidden rounded-lg">
        <img ref={imgRef} src={src} alt="submitted label" className="block w-full" />
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
                fill={VERDICT[highlight.verdict].hex} fillOpacity={0.22}
                stroke={VERDICT[highlight.verdict].hex} strokeWidth={3}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
