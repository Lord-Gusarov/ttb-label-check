import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { decide, listApplications } from "../api";
import type { AppSummary } from "../types";
import { PageHeading, StatusBadge, VerdictPill } from "../ui";

const COMMODITY: Record<string, string> = {
  distilled_spirits: "Distilled spirits",
  wine: "Wine",
  malt_beverage: "Malt beverage",
};

export function QueuePage() {
  const [apps, setApps] = useState<AppSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  function refresh() {
    listApplications().then(setApps).catch(() => setApps([]));
  }
  useEffect(refresh, []);

  async function approve(ids: string[]) {
    setBusy(true);
    try {
      for (const id of ids) await decide(id, "approved", "");
      refresh();
    } finally {
      setBusy(false);
    }
  }

  if (apps === null) return <p className="mt-8 text-muted">Loading…</p>;

  const submitted = apps.filter((a) => a.status === "submitted");
  const clear = submitted.filter((a) => a.overall === "pass");
  const attention = submitted.filter((a) => a.overall !== "pass");
  const decided = apps.filter((a) => a.status !== "submitted");

  return (
    <div className="rise space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeading title="Review queue" subtitle="The tool recommends; you decide. Clear the easy ones fast, focus on the flagged." />
        <Link to="/submit" className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">
          + New application
        </Link>
      </div>

      {submitted.length === 0 && decided.length === 0 && <EmptyState />}

      {attention.length > 0 && (
        <Section
          title={`Needs your attention (${attention.length})`}
          subtitle="Automated checks flagged something — open to review the evidence and decide."
        >
          <Table apps={attention} onOpen={(id) => navigate(`/queue/${id}`)} />
        </Section>
      )}

      {clear.length > 0 && (
        <Section
          title={`Recommended to approve (${clear.length})`}
          subtitle="Every automated check passed. Glance and clear — or approve them all."
          action={
            <button
              disabled={busy}
              onClick={() => approve(clear.map((a) => a.id))}
              className="rounded-md bg-pass px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
            >
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
                className="rounded-md border border-pass px-3 py-1 text-xs font-semibold text-pass transition hover:bg-pass-soft disabled:opacity-50"
              >
                Approve
              </button>
            )}
          />
        </Section>
      )}

      {decided.length > 0 && (
        <Section title="Decided" subtitle="Already approved or rejected.">
          <Table apps={decided} onOpen={(id) => navigate(`/queue/${id}`)} />
        </Section>
      )}
    </div>
  );
}

function Section({ title, subtitle, action, children }: {
  title: string; subtitle: string; action?: ReactNode; children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-serif text-lg font-semibold text-ink">{title}</h2>
          <p className="text-sm text-muted">{subtitle}</p>
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
    <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-sm">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
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
            <tr key={a.id} onClick={() => onOpen(a.id)} className="cursor-pointer transition hover:bg-paper">
              <td className="px-5 py-4 font-medium text-ink">
                <Link to={`/queue/${a.id}`} className="hover:text-brand" onClick={(e) => e.stopPropagation()}>
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
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-line bg-surface p-12 text-center">
      <p className="font-serif text-lg text-ink">No applications yet</p>
      <p className="mt-1 text-muted">Submit a label to start a review.</p>
      <Link to="/submit" className="mt-4 inline-block rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">
        Submit an application
      </Link>
    </div>
  );
}
