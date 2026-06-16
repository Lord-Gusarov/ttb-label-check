import type { ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./ErrorBoundary";
import { SubmitPage } from "./pages/SubmitPage";
import { QueuePage } from "./pages/QueuePage";
import { ReviewPage } from "./pages/ReviewPage";
import { BatchPage } from "./pages/BatchPage";
import { BatchProgressPage } from "./pages/BatchProgressPage";

const NAV = [
  { to: "/submit", label: "Submit application", icon: <PlusIcon /> },
  { to: "/batch", label: "Batch upload", icon: <PlusIcon /> },
  { to: "/queue", label: "Review queue", icon: <ListIcon /> },
];

export default function App() {
  return (
    <div className="flex min-h-full">
      <a href="#main" className="skip-link">Skip to content</a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 md:px-10 md:py-10">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Navigate to="/submit" replace />} />
              <Route path="/submit" element={<SubmitPage />} />
              <Route path="/batch" element={<BatchPage />} />
              <Route path="/batch/:id" element={<BatchProgressPage />} />
              <Route path="/queue" element={<QueuePage />} />
              <Route path="/queue/:id" element={<ReviewPage />} />
              <Route path="*" element={<Navigate to="/submit" replace />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-surface/80 backdrop-blur md:flex">
      <div className="flex items-center gap-3 px-6 py-6">
        <Seal />
        <div>
          <div className="text-[15px] font-bold leading-tight tracking-tight text-ink">Label Check</div>
          <div className="text-xs text-muted">TTB label verification</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3">
        {NAV.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) =>
              `group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-brand-soft text-brand"
                  : "text-muted hover:bg-paper hover:text-ink"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  aria-hidden
                  className={`absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-brand transition-opacity ${
                    isActive ? "opacity-100" : "opacity-0"
                  }`}
                />
                <span aria-hidden className="grid h-5 w-5 place-items-center">{l.icon}</span>
                {l.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="m-3 rounded-lg bg-paper px-4 py-3 text-xs leading-relaxed text-muted">
        <span className="font-semibold text-ink">Standalone prototype</span>
        <br />Local-first · nothing stored.
      </div>
    </aside>
  );
}

function TopBar() {
  const { pathname } = useLocation();
  const crumb = pathname.startsWith("/submit")
    ? "Submit application"
    : pathname.startsWith("/batch/")
      ? "Batch upload / Progress"
      : pathname.startsWith("/batch")
        ? "Batch upload"
        : pathname.startsWith("/queue/")
          ? "Review queue / Application"
          : "Review queue";
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-3.5 text-sm md:px-10">
        <span className="flex items-center gap-2 font-bold tracking-tight text-ink md:hidden">
          <Seal small /> Label Check
        </span>
        <Breadcrumb crumb={crumb} />
      </div>
    </header>
  );
}

function Breadcrumb({ crumb }: { crumb: string }) {
  const parts = crumb.split(" / ");
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-muted">
      {parts.map((p, i) => (
        <span key={p} className="flex items-center gap-1.5">
          {i > 0 && <span aria-hidden className="text-line-strong">/</span>}
          <span className={i === parts.length - 1 ? "font-semibold text-ink" : ""}>{p}</span>
        </span>
      ))}
    </nav>
  );
}

function Seal({ small }: { small?: boolean }) {
  const size = small ? "h-7 w-7 text-[11px]" : "h-10 w-10 text-sm";
  return (
    <div
      aria-hidden
      className={`grid shrink-0 place-items-center rounded-xl bg-brand font-serif font-bold text-white shadow-card ring-1 ring-white/10 ${size}`}
    >
      LC
    </div>
  );
}

function IconWrap({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-[18px] w-[18px]" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}
function PlusIcon() {
  return <IconWrap><path d="M10 4.5v11M4.5 10h11" /></IconWrap>;
}
function ListIcon() {
  return (
    <IconWrap>
      <path d="M7 6h9M7 10h9M7 14h9" />
      <circle cx="3.5" cy="6" r="0.6" fill="currentColor" />
      <circle cx="3.5" cy="10" r="0.6" fill="currentColor" />
      <circle cx="3.5" cy="14" r="0.6" fill="currentColor" />
    </IconWrap>
  );
}
