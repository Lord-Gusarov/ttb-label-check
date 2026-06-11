import type { ReactNode } from "react";
import type { Verdict } from "./types";

export const VERDICT: Record<Verdict, { label: string; cls: string; hex: string }> = {
  pass: { label: "Pass", cls: "text-pass bg-pass-soft", hex: "#1f7a4d" },
  warn: { label: "Review", cls: "text-flag bg-flag-soft", hex: "#a36400" },
  needs_review: { label: "Review", cls: "text-flag bg-flag-soft", hex: "#a36400" },
  fail: { label: "Fail", cls: "text-fail bg-fail-soft", hex: "#b42318" },
};

const STATUS: Record<string, { label: string; cls: string }> = {
  submitted: { label: "Awaiting review", cls: "bg-brand-soft text-brand" },
  approved: { label: "Approved", cls: "bg-pass-soft text-pass" },
  needs_correction: { label: "Needs correction", cls: "bg-flag-soft text-flag" },
  rejected: { label: "Rejected", cls: "bg-fail-soft text-fail" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-paper text-muted" };
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function VerdictPill({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict];
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide ${v.cls}`}>
      {v.label}
    </span>
  );
}

export function PageHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <h1 className="font-serif text-2xl font-semibold text-ink">{title}</h1>
      {subtitle && <p className="mt-1 text-muted">{subtitle}</p>}
    </div>
  );
}

export const inputCls =
  "w-full rounded-md border border-line bg-paper px-3 py-2.5 text-base text-ink outline-none transition focus:border-brand";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-ink">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}
