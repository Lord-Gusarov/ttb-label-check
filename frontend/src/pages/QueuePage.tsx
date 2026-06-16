import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { decide, listApplications } from "../api";
import type { AppSummary } from "../types";
import { Card, PageHeading, StatusBadge, Tabs, VerdictPill, btnOutlinePass, btnPass, btnPrimary, formatWhen } from "../ui";

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
  const [params, setParams] = useSearchParams();

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
  const verifying = apps.filter((a) => a.status === "submitted" && a.verify_status !== "verified" && a.verify_status !== "error");
  const verified = apps.filter((a) => a.status === "submitted" && (a.verify_status === "verified" || a.verify_status === "error"));
  const clear = verified.filter((a) => a.overall === "pass");
  const attention = verified.filter((a) => a.overall !== "pass");
  const decided = apps.filter((a) => a.status !== "submitted");

  const tabs = [
    { key: "attention", label: "Needs attention", count: attention.length },
    { key: "approve", label: "Recommended to approve", count: clear.length },
    { key: "verifying", label: "Verifying", count: verifying.length },
    { key: "decided", label: "Decided", count: decided.length },
  ];
  const raw = params.get("tab") ?? "attention";
  const active = tabs.some((t) => t.key === raw) ? raw : "attention";
  const setTab = (key: string) => setParams({ tab: key }, { replace: true });
  const panelId = "queue-panel";

  const heading = (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <PageHeading title="Review queue" subtitle="The tool recommends; you decide." />
      <Link to="/submit" className={`${btnPrimary} px-4 py-2.5 text-sm`}>+ New application</Link>
    </div>
  );

  if (apps.length === 0) {
    return (
      <div className="rise space-y-6">
        {heading}
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="rise space-y-6">
      {heading}

      {error && (
        <p role="alert" className="rounded-lg border border-fail/30 bg-fail/5 px-4 py-3 text-sm font-medium text-fail">
          Action failed: {error}
        </p>
      )}

      <Tabs tabs={tabs} active={active} onChange={setTab} panelId={panelId} />

      <div id={panelId} role="tabpanel" aria-labelledby={`${panelId}-tab-${active}`} tabIndex={0} className="space-y-3">
        {active === "attention" && (attention.length
          ? <Table apps={attention} onOpen={(id) => navigate(`/queue/${id}`)} />
          : <Empty msg="Nothing flagged. 🎉" />)}
        {active === "approve" && (clear.length ? (
          <>
            <div className="flex justify-end">
              <button disabled={busy} onClick={() => approve(clear.map((a) => a.id))} className={`${btnPass} px-4 py-2.5 text-sm`}>
                {busy ? "Approving…" : `Approve all ${clear.length}`}
              </button>
            </div>
            <Table apps={clear} onOpen={(id) => navigate(`/queue/${id}`)}
              rowAction={(a) => (
                <button disabled={busy} onClick={(e) => { e.stopPropagation(); approve([a.id]); }} className={`${btnOutlinePass} px-3 py-1.5 text-xs`}>
                  Approve
                </button>
              )} />
          </>
        ) : <Empty msg="No clear applications waiting." />)}
        {active === "verifying" && (verifying.length
          ? <Table apps={verifying} onOpen={(id) => navigate(`/queue/${id}`)} />
          : <Empty msg="Nothing in progress." />)}
        {active === "decided" && (decided.length
          ? <Table apps={decided} onOpen={(id) => navigate(`/queue/${id}`)} />
          : <Empty msg="No decisions yet." />)}
      </div>
    </div>
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
            <th className="hidden px-5 py-3 font-semibold md:table-cell">Submitted</th>
            <th className="px-5 py-3 text-right font-semibold">Status</th>
            {rowAction && <th className="px-5 py-3 text-right font-semibold">Action</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {[...apps].sort((x, y) => y.created_at - x.created_at).map((a) => (
            <tr key={a.id} onClick={() => onOpen(a.id)} className="cursor-pointer transition hover:bg-brand-soft/40">
              <td className="px-5 py-4 font-semibold text-ink">
                <Link to={`/queue/${a.id}`} className="rounded hover:text-brand hover:underline" onClick={(e) => e.stopPropagation()}>
                  {a.brand_name}
                </Link>
              </td>
              <td className="hidden px-5 py-4 text-muted sm:table-cell">{COMMODITY[a.commodity_type] ?? a.commodity_type}</td>
              <td className="px-5 py-4">
                {a.verify_status === "verified" && a.overall != null ? <VerdictPill verdict={a.overall} />
                  : a.verify_status === "error" ? <span className="text-xs font-medium text-fail">Error</span>
                  : <span className="text-xs text-muted">Verifying…</span>}
              </td>
              <td className="hidden px-5 py-4 text-muted md:table-cell">{formatWhen(a.created_at)}</td>
              <td className="px-5 py-4 text-right"><StatusBadge status={a.status} /></td>
              {rowAction && <td className="px-5 py-4 text-right">{rowAction(a)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Empty({ msg }: { msg: string }) {
  return <p className="px-1 py-8 text-center text-muted">{msg}</p>;
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
