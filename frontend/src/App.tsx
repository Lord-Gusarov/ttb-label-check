import { useEffect, useState } from 'react'

type Health = { status: string; version: string }

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-6 py-5 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Label Check</h1>
            <p className="text-slate-500">TTB alcohol label verification</p>
          </div>
          <ApiBadge health={health} error={error} />
        </div>
      </header>

      <main className="mx-auto max-w-5xl w-full px-6 py-12 flex-1">
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <h2 className="text-xl font-medium text-slate-800">Upload a label to begin</h2>
          <p className="mt-2 text-slate-500">
            Single review and batch upload are coming next. This is the project shell.
          </p>
        </div>
      </main>
    </div>
  )
}

function ApiBadge({ health, error }: { health: Health | null; error: string | null }) {
  if (error) {
    return (
      <span className="rounded-full bg-red-100 px-3 py-1 text-sm font-medium text-red-700">
        API offline
      </span>
    )
  }
  if (!health) {
    return (
      <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-600">
        Connecting…
      </span>
    )
  }
  return (
    <span className="rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-700">
      API ok · v{health.version}
    </span>
  )
}

export default App
