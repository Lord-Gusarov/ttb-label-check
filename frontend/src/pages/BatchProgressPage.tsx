// frontend/src/pages/BatchProgressPage.tsx
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { getBatch } from "../api";
import type { BatchProgress, BatchSkip } from "../types";
import { Card, PageHeading, VerdictPill, btnPrimary } from "../ui";

export function BatchProgressPage() {
  const { id = "" } = useParams();
  const skipped = (useLocation().state as { skipped?: BatchSkip[] } | null)?.skipped ?? [];
  const [prog, setProg] = useState<BatchProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        const p = await getBatch(id);
        if (!live) return;
        setProg(p);
        if (p.counts.pending + p.counts.verifying > 0) timer = setTimeout(tick, 1500);
      } catch (e) { if (live) setError(String(e)); }
    }
    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [id]);

  if (error) return <Card className="mt-8 border-fail/30 p-8 text-center"><p role="alert" className="font-medium text-fail">{error}</p></Card>;
  if (!prog) return <p className="mt-8 text-muted">Loading…</p>;

  const done = prog.counts.verified + prog.counts.error;
  const clear = prog.items.filter((a) => a.verify_status === "verified" && a.overall === "pass").length;
  const attention = prog.items.filter((a) => a.verify_status === "verified" && a.overall !== "pass").length;
  const complete = prog.counts.pending + prog.counts.verifying === 0;

  return (
    <div className="rise space-y-6">
      <PageHeading title="Batch" subtitle={`${done} / ${prog.total} verified`} />

      {skipped.length > 0 && (
        <details className="rounded-lg border border-flag/40 bg-flag/5 px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium text-ink">{skipped.length} rows skipped — see why</summary>
          <ul className="mt-2 space-y-1 text-muted">
            {skipped.map((s) => <li key={s.index}>Row {s.index + 1} ({s.image ?? "no image"}): {s.reason}</li>)}
          </ul>
        </details>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Clear" value={clear} tone="text-pass" />
        <Stat label="Needs attention" value={attention} tone="text-flag" />
        <Stat label="Verifying" value={prog.counts.pending + prog.counts.verifying} tone="text-muted" />
        <Stat label="Errors" value={prog.counts.error} tone="text-fail" />
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-surface-2 text-xs uppercase tracking-wide text-muted">
            <tr><th className="px-5 py-3 font-semibold">Brand</th><th className="px-5 py-3 font-semibold">Check</th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {prog.items.map((a) => (
              <tr key={a.id}>
                <td className="px-5 py-3 font-semibold text-ink">
                  <Link to={`/queue/${a.id}`} className="hover:text-brand hover:underline">{a.brand_name}</Link>
                </td>
                <td className="px-5 py-3">
                  {a.verify_status === "verified" && a.overall != null ? <VerdictPill verdict={a.overall} />
                    : a.verify_status === "error" ? <span className="text-xs font-medium text-fail">Error</span>
                    : <span className="text-xs text-muted">Verifying…</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {complete && (
        <div className="flex items-center gap-3">
          <p className="text-sm font-medium text-ink">{clear} clear · {attention} need attention · {prog.counts.error} errors</p>
          <Link to="/queue?tab=attention" className={`${btnPrimary} px-4 py-2.5 text-sm`}>Go to review queue</Link>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className={`text-2xl font-bold ${tone}`}>{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  );
}
