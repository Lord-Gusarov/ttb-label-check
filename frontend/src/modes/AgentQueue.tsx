import { useEffect, useState } from "react";
import { listApplications } from "../api";
import type { AppSummary } from "../types";
import { ReviewView } from "./ReviewView";

const STATUS_COLOR: Record<string, string> = {
  submitted: "bg-slate-100 text-slate-700", approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700", needs_correction: "bg-amber-100 text-amber-700",
};

export function AgentQueue() {
  const [apps, setApps] = useState<AppSummary[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  const refresh = () => listApplications().then(setApps).catch(() => setApps([]));
  useEffect(() => { refresh(); }, []);

  if (openId) return <ReviewView id={openId} onBack={() => { setOpenId(null); refresh(); }} />;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-medium text-slate-800">Review queue</h2>
      {apps.length === 0 && <p className="text-slate-500">No applications yet. Submit one from "Submit application".</p>}
      <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        {apps.map((a) => (
          <li key={a.id}>
            <button onClick={() => setOpenId(a.id)}
              className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-slate-50">
              <span className="font-medium text-slate-800">{a.brand_name}</span>
              <span className={`rounded-full px-3 py-1 text-sm font-medium ${STATUS_COLOR[a.status] ?? ""}`}>
                {a.status.replaceAll("_", " ")}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
