import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./ErrorBoundary";
import { SubmitPage } from "./pages/SubmitPage";
import { QueuePage } from "./pages/QueuePage";
import { ReviewPage } from "./pages/ReviewPage";

const NAV = [
  { to: "/queue", label: "Review queue", glyph: "▤" },
  { to: "/submit", label: "Submit application", glyph: "＋" },
];

export default function App() {
  return (
    <div className="flex min-h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 md:px-10">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Navigate to="/queue" replace />} />
              <Route path="/submit" element={<SubmitPage />} />
              <Route path="/queue" element={<QueuePage />} />
              <Route path="/queue/:id" element={<ReviewPage />} />
              <Route path="*" element={<Navigate to="/queue" replace />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-surface md:flex">
      <div className="flex items-center gap-3 border-b border-line px-6 py-5">
        <Seal />
        <div>
          <div className="font-serif text-lg font-semibold leading-tight text-ink">Label Check</div>
          <div className="text-xs text-muted">TTB label verification</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive ? "bg-brand-soft text-brand" : "text-muted hover:bg-paper hover:text-ink"
              }`
            }
          >
            <span aria-hidden className="w-4 text-center text-base leading-none">{l.glyph}</span>
            {l.label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-line px-6 py-4 text-xs leading-relaxed text-muted">
        Standalone prototype.<br />Local-first · nothing stored.
      </div>
    </aside>
  );
}

function TopBar() {
  const { pathname } = useLocation();
  const crumb = pathname.startsWith("/submit")
    ? "Submit application"
    : pathname.startsWith("/queue/")
      ? "Review queue / Application"
      : "Review queue";
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-surface/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-3 text-sm md:px-10">
        <span className="font-serif font-semibold text-ink md:hidden">Label Check</span>
        <span className="text-muted">{crumb}</span>
      </div>
    </header>
  );
}

function Seal() {
  return (
    <div className="flex h-9 w-9 items-center justify-center rounded-full border-2 border-brand text-brand">
      <span className="font-serif text-sm font-bold">LC</span>
    </div>
  );
}
