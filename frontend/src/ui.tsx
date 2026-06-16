import { type ReactNode } from "react";
import type { Verdict } from "./types";

// `cls` styles the chip; `dot` tints the status dot; `hex` is the on-image overlay color.
export const VERDICT: Record<Verdict, { label: string; cls: string; dot: string; hex: string }> = {
  pass: { label: "Pass", cls: "bg-pass-soft text-pass ring-pass/20", dot: "bg-pass", hex: "#15663f" },
  warn: { label: "Review", cls: "bg-flag-soft text-flag ring-flag/20", dot: "bg-flag", hex: "#8a5200" },
  needs_review: { label: "Review", cls: "bg-flag-soft text-flag ring-flag/20", dot: "bg-flag", hex: "#8a5200" },
};

const STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  submitted: { label: "Awaiting review", cls: "bg-brand-soft text-brand ring-brand/15", dot: "bg-brand" },
  approved: { label: "Approved", cls: "bg-pass-soft text-pass ring-pass/20", dot: "bg-pass" },
  needs_correction: { label: "Needs correction", cls: "bg-flag-soft text-flag ring-flag/20", dot: "bg-flag" },
  rejected: { label: "Rejected", cls: "bg-fail-soft text-fail ring-fail/20", dot: "bg-fail" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-paper text-muted ring-line", dot: "bg-muted" };
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${s.cls}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

export function VerdictPill({ verdict }: { verdict: Verdict }) {
  const v = VERDICT[verdict];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ring-1 ring-inset ${v.cls}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${v.dot}`} />
      {v.label}
    </span>
  );
}

export function PageHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="max-w-2xl">
      <h1 className="font-serif text-[1.9rem] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
      {subtitle && <p className="mt-2 text-[15px] leading-relaxed text-muted">{subtitle}</p>}
    </div>
  );
}

export const inputCls =
  "w-full rounded-lg border border-line bg-paper px-3.5 py-2.5 text-base text-ink shadow-sm outline-none transition " +
  "placeholder:text-faint hover:border-line-strong focus:border-brand focus:bg-surface focus:ring-4 focus:ring-brand-soft";

// Reusable button styles (shared so every action looks and behaves the same).
const btnBase =
  "inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition " +
  "active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55";
export const btnPrimary = `${btnBase} bg-brand text-white shadow-card hover:brightness-110`;
export const btnPass = `${btnBase} bg-pass text-white shadow-card hover:brightness-110`;
export const btnFail = `${btnBase} bg-fail text-white shadow-card hover:brightness-110`;
export const btnOutlinePass = `${btnBase} border border-pass/40 text-pass hover:bg-pass-soft`;
export const btnGhost = `${btnBase} border border-line bg-surface text-ink hover:border-line-strong hover:bg-paper`;

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-ink">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-line bg-surface shadow-card ${className}`}>{children}</div>
  );
}

/** Friendly submitted-at label from an epoch-seconds timestamp. */
export function formatWhen(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export interface TabDef { key: string; label: string; count: number; }

/** WCAG-AA tablist: roving focus, arrow-key navigation, aria-selected. */
export function Tabs({ tabs, active, onChange, panelId }: {
  tabs: TabDef[]; active: string; onChange: (key: string) => void; panelId: string;
}) {
  function onKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    onChange(tabs[next].key);
    // Roving tabindex: focus must follow selection on keyboard nav (focus() ignores the
    // current tabIndex=-1). We move focus here, not in an effect, so initial render and
    // mouse clicks don't steal focus.
    document.getElementById(`${panelId}-tab-${tabs[next].key}`)?.focus();
  }
  return (
    <div role="tablist" aria-label="Queue filters" className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t, i) => {
        const selected = t.key === active;
        return (
          <button
            key={t.key}
            role="tab"
            id={`${panelId}-tab-${t.key}`}
            aria-selected={selected}
            aria-controls={panelId}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => onKey(e, i)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              selected ? "border-brand text-brand" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t.label}
            <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
              selected ? "bg-brand-soft text-brand" : "bg-surface-2 text-muted"
            }`}>{t.count}</span>
          </button>
        );
      })}
    </div>
  );
}
