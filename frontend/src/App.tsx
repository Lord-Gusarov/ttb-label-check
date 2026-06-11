import { useState } from "react";
import { ApplicantForm } from "./modes/ApplicantForm";
import { AgentQueue } from "./modes/AgentQueue";
import { ErrorBoundary } from "./ErrorBoundary";

type Mode = "applicant" | "agent";

export default function App() {
  const [mode, setMode] = useState<Mode>("agent");
  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-slate-900">Label Check</h1>
          <nav className="flex gap-1 rounded-lg bg-slate-100 p-1" role="tablist">
            {(["applicant", "agent"] as Mode[]).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`px-4 py-2 rounded-md text-sm font-medium ${
                  mode === m ? "bg-white text-slate-900 shadow" : "text-slate-600"}`}>
                {m === "applicant" ? "Submit application" : "Agent review"}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl w-full px-6 py-8 flex-1">
        <ErrorBoundary>
          {mode === "applicant" ? <ApplicantForm /> : <AgentQueue />}
        </ErrorBoundary>
      </main>
    </div>
  );
}
