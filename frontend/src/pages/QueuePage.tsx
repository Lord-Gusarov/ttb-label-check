import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listApplications } from "../api";
import type { AppSummary } from "../types";
import { PageHeading, StatusBadge } from "../ui";

const COMMODITY: Record<string, string> = {
  distilled_spirits: "Distilled spirits",
  wine: "Wine",
  malt_beverage: "Malt beverage",
};

export function QueuePage() {
  const [apps, setApps] = useState<AppSummary[] | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    listApplications().then(setApps).catch(() => setApps([]));
  }, []);

  return (
    <div className="rise">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageHeading title="Review queue" subtitle="Applications awaiting a compliance decision." />
        <Link to="/submit" className="rounded-md bg-brand px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">
          + New application
        </Link>
      </div>

      {apps === null ? (
        <p className="mt-8 text-muted">Loading…</p>
      ) : apps.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="mt-6 overflow-hidden rounded-xl border border-line bg-surface shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-5 py-3 font-semibold">Brand</th>
                <th className="px-5 py-3 font-semibold">Type</th>
                <th className="hidden px-5 py-3 font-semibold sm:table-cell">Submitted</th>
                <th className="px-5 py-3 text-right font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {apps.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => navigate(`/queue/${a.id}`)}
                  className="cursor-pointer transition hover:bg-paper"
                >
                  <td className="px-5 py-4 font-medium text-ink">
                    <Link to={`/queue/${a.id}`} className="hover:text-brand" onClick={(e) => e.stopPropagation()}>
                      {a.brand_name}
                    </Link>
                  </td>
                  <td className="px-5 py-4 text-muted">{COMMODITY[a.commodity_type] ?? a.commodity_type}</td>
                  <td className="hidden px-5 py-4 text-muted sm:table-cell">
                    {new Date(a.created_at * 1000).toLocaleString()}
                  </td>
                  <td className="px-5 py-4 text-right"><StatusBadge status={a.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
