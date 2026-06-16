import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { decide, listApplications } from "../api";
import type { AppSummary } from "../types";
import { Card, PageHeading, StatusBadge, VerdictPill, btnOutlinePass, btnPass, btnPrimary } from "../ui";

const COMMODITY: Record<string, string> = {
  distilled_spirits: "Distilled spirits",
  wine: "Wine",
  malt_beverage: "Malt beverage",
};

export function QueuePage() {
  const [apps, setApps] = useState<AppSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  function refresh() {
    listApplications()
      .then((a) => { setApps(a); setError(null); })
      .catch((e) => setError(String(e)));
  }
  useEffect(refresh, []);

  async function approve(ids: string[]) {
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) await decide(id, "approved", "");
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Distinguish "couldn't load" from "nothing here": only an actual fetch failure
  // (apps never arrived) shows the error screen; a successful empty load shows EmptyState.
  if (apps === null)
    return error ? (
      <Card className="mt-8 border-fail/30 p-8 text-center">
        <p role="alert" className="font-medium text-fail">Could not load the queue: {error}</p>
        <button onClick={refresh} className={`${btnPrimary} mt-4 px-4 py-2.5 text-sm`}>Try again</button>
      </Card>
    ) : (
      <p className="mt-8 text-muted">Loading…</p>
    );

  const submitted = apps.filter((a) => a.status === "submitted");
  const clear = submitted.filter((a) => a.overall === "pass");
  const attention = submitted.filter((a) => a.overall !== "pass");
  const decided = apps.filter((a) => a.status !== "submitted");

  return (
    <div className="rise space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeading title="Review queue" subtitle="The tool recommends; you decide. Clear the easy ones fast, focus on the flagged." />
        <Link to="/submit" className={`${btnPrimary} px-4 py-2.5 text-sm`}>+ New application</Link>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-fail/30 bg-fail/5 px-4 py-3 text-sm font-medium text-fail">
          Action failed: {error}
        </p>
      )}

      {submitted.length === 0 && decided.length === 0 && <EmptyState />}

      <div className="stagger space-y-8">
        {attention.length > 0 && (
          <Section
            tone="flag"
            title={`Needs your attention (${attention.length})`}
            subtitle="Automated checks flagged something — open to review the evidence and decide."
          >
            <Table apps={attention} onOpen={(id) => navigate(`/queue/${id}`)} />
          </Section>
        )}

        {clear.length > 0 && (
          <Section
            tone="pass"
            title={`Recommended to approve (${clear.length})`}
            subtitle="Every automated check passed. Glance and clear — or approve them all."
            action={
              <button disabled={busy} onClick={() => approve(clear.map((a) => a.id))} className={`${btnPass} px-4 py-2.5 text-sm`}>
                {busy ? "Approving…" : `Approve all ${clear.length}`}
              </button>
            }
          >
            <Table
              apps={clear}
              onOpen={(id) => navigate(`/queue/${id}`)}
              rowAction={(a) => (
                <button
                  disabled={busy}
                  onClick={(e) => { e.stopPropagation(); approve([a.id]); }}
                  className={`${btnOutlinePass} px-3 py-1.5 text-xs`}
                >
                  Approve
                </button>
              )}
            />
          </Section>
        )}

        {decided.length > 0 && (
          <Section tone="muted" title="Decided" subtitle="Already approved or rejected.">
            <Table apps={decided} onOpen={(id) => navigate(`/queue/${id}`)} />
          </Section>
        )}
      </div>
    </div>
  );
}

const TONE: Record<string, string> = { flag: "bg-flag", pass: "bg-pass", muted: "bg-line-strong" };

function Section({ title, subtitle, action, tone = "muted", children }: {
  title: string; subtitle: string; action?: ReactNode; tone?: string; children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-start gap-2.5">
          <span aria-hidden className={`mt-1 h-5 w-1.5 shrink-0 rounded-full ${TONE[tone]}`} />
          <div>
            <h2 className="text-base font-bold tracking-tight text-ink">{title}</h2>
            <p className="text-sm text-muted">{subtitle}</p>
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Table({ apps, onOpen, rowAction }: {
  apps: AppSummary[];
  onOpen: (id: string) => void;
  rowAction?: (a: AppSummary) => ReactNode;
}) {
  return (
    <Card className="overflow-hidden">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="px-5 py-3 font-semibold">Brand</th>
            <th className="hidden px-5 py-3 font-semibold sm:table-cell">Type</th>
            <th className="px-5 py-3 font-semibold">Check</th>
            <th className="px-5 py-3 text-right font-semibold">Status</th>
            {rowAction && <th className="px-5 py-3 text-right font-semibold">Action</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {apps.map((a) => (
            <tr key={a.id} onClick={() => onOpen(a.id)} className="cursor-pointer transition hover:bg-brand-soft/40">
              <td className="px-5 py-4 font-semibold text-ink">
                <Link to={`/queue/${a.id}`} className="rounded hover:text-brand hover:underline" onClick={(e) => e.stopPropagation()}>
                  {a.brand_name}
                </Link>
              </td>
              <td className="hidden px-5 py-4 text-muted sm:table-cell">{COMMODITY[a.commodity_type] ?? a.commodity_type}</td>
              <td className="px-5 py-4">{a.overall ? <VerdictPill verdict={a.overall} /> : <span className="text-xs text-muted">—</span>}</td>
              <td className="px-5 py-4 text-right"><StatusBadge status={a.status} /></td>
              {rowAction && <td className="px-5 py-4 text-right">{rowAction(a)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card className="mt-6 border-dashed p-12 text-center">
      <p className="font-serif text-xl text-ink">No applications yet</p>
      <p className="mt-1 text-muted">Submit a label to start a review.</p>
      <Link to="/submit" className={`${btnPrimary} mt-5 px-4 py-2.5 text-sm`}>Submit an application</Link>
    </Card>
  );
}
