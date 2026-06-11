import { useState } from "react";
import { submitApplication } from "../api";

const FIELDS = [
  { name: "brand_name", label: "Brand name", placeholder: "OLD TOM DISTILLERY" },
  { name: "class_type", label: "Class / type", placeholder: "Kentucky Straight Bourbon Whiskey" },
  { name: "alcohol_content", label: "Alcohol content", placeholder: "45% Alc./Vol. (90 Proof)" },
  { name: "net_contents", label: "Net contents", placeholder: "750 mL" },
];

export function ApplicantForm() {
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const { id } = await submitApplication(new FormData(e.currentTarget));
      setDone(id); e.currentTarget.reset();
    } catch (err) { setError(String(err)); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-xl space-y-5">
      <h2 className="text-xl font-medium text-slate-800">Submit a label for approval</h2>
      <label className="block">
        <span className="text-slate-700">Product type</span>
        <select name="commodity_type" defaultValue="distilled_spirits"
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-lg">
          <option value="distilled_spirits">Distilled spirits</option>
          <option value="wine">Wine</option>
          <option value="malt_beverage">Malt beverage</option>
        </select>
      </label>
      {FIELDS.map((f) => (
        <label key={f.name} className="block">
          <span className="text-slate-700">{f.label}</span>
          <input name={f.name} required placeholder={f.placeholder}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-lg" />
        </label>
      ))}
      <label className="block">
        <span className="text-slate-700">Label image</span>
        <input type="file" name="image" accept="image/png,image/jpeg" required
          className="mt-1 block w-full text-slate-700" />
      </label>
      <button disabled={busy}
        className="rounded-md bg-blue-600 px-5 py-3 text-lg font-medium text-white disabled:opacity-50">
        {busy ? "Submitting…" : "Submit application"}
      </button>
      {done && <p className="text-green-700">Submitted. Application id <code>{done}</code> is now in the agent queue.</p>}
      {error && <p className="text-red-700">Could not submit: {error}</p>}
    </form>
  );
}
