// frontend/src/pages/BatchPage.tsx
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadBatch } from "../api";
import { Card, PageHeading, btnPrimary, inputCls } from "../ui";

interface Reconciliation { count: number; missing: string[]; unreferenced: string[]; error: string | null; }

function reconcile(manifestText: string | null, imageNames: Set<string>): Reconciliation {
  if (manifestText === null) return { count: 0, missing: [], unreferenced: [], error: null };
  let rows: unknown;
  try { rows = JSON.parse(manifestText); }
  catch { return { count: 0, missing: [], unreferenced: [], error: "Manifest is not valid JSON." }; }
  if (!Array.isArray(rows)) return { count: 0, missing: [], unreferenced: [], error: "Manifest must be a JSON array." };
  const referenced = rows.map((r) => (r && typeof r === "object" ? String((r as Record<string, unknown>).image ?? "") : ""));
  const missing = [...new Set(referenced.filter((n) => n && !imageNames.has(n)))];
  const refSet = new Set(referenced);
  const unreferenced = [...imageNames].filter((n) => !refSet.has(n));
  return { count: rows.length, missing, unreferenced, error: null };
}

export function BatchPage() {
  const [manifest, setManifest] = useState<File | null>(null);
  const [manifestText, setManifestText] = useState<string | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const imageNames = useMemo(() => new Set(images.map((f) => f.name)), [images]);
  const rec = useMemo(() => reconcile(manifestText, imageNames), [manifestText, imageNames]);
  const ready = manifest !== null && rec.error === null && rec.count > 0 && rec.missing.length === 0;

  async function onManifest(file: File | null) {
    setManifest(file);
    setManifestText(file ? await file.text() : null);
  }

  async function submit() {
    if (!manifest) return;
    setBusy(true); setError(null);
    try {
      const res = await uploadBatch(manifest, images);
      navigate(`/batch/${res.batch_id}`, { state: { skipped: res.skipped } });
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="rise space-y-6">
      <PageHeading title="Batch upload" subtitle="Upload a JSON manifest and the label images. Each manifest entry names its image file." />
      <Card className="space-y-5 p-6">
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Manifest (.json)</span>
          <input type="file" accept="application/json,.json" className={inputCls}
            onChange={(e) => onManifest(e.currentTarget.files?.[0] ?? null)} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink">Label images</span>
          <input type="file" accept="image/png,image/jpeg" multiple className={inputCls}
            onChange={(e) => setImages([...(e.currentTarget.files ?? [])])} />
        </label>

        {manifestText !== null && (
          <div role="status" className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm">
            {rec.error ? (
              <p className="font-medium text-fail">{rec.error}</p>
            ) : (
              <>
                <p className="font-medium text-ink">
                  Manifest: {rec.count} applications · {images.length} images
                  {ready && <span className="text-pass"> · all matched ✓</span>}
                </p>
                {rec.missing.length > 0 && (
                  <p className="mt-1 text-fail">Rows reference images you didn't include: {rec.missing.join(", ")}</p>
                )}
                {rec.unreferenced.length > 0 && (
                  <p className="mt-1 text-muted">Images not referenced by any row: {rec.unreferenced.join(", ")}</p>
                )}
              </>
            )}
          </div>
        )}

        <button disabled={!ready || busy} onClick={submit} className={`${btnPrimary} px-5 py-3 text-base disabled:opacity-50`}>
          {busy ? "Uploading…" : `Upload ${rec.count || ""} applications`.trim()}
        </button>
        {error && <p role="alert" className="text-sm font-medium text-fail">Could not upload: {error}</p>}
      </Card>
    </div>
  );
}
