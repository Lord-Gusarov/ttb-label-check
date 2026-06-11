import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { submitApplication } from "../api";
import { Field, PageHeading, inputCls } from "../ui";

const FIELDS = [
  { name: "brand_name", label: "Brand name", placeholder: "OLD TOM DISTILLERY" },
  { name: "class_type", label: "Class / type designation", placeholder: "Kentucky Straight Bourbon Whiskey" },
  { name: "alcohol_content", label: "Alcohol content", placeholder: "45% Alc./Vol. (90 Proof)" },
  { name: "net_contents", label: "Net contents", placeholder: "750 mL" },
];

export function SubmitPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget; // capture before await
    setBusy(true);
    setError(null);
    try {
      const { id } = await submitApplication(new FormData(form));
      navigate(`/queue/${id}`); // go straight to the review of what was just submitted
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  }

  return (
    <div className="rise mx-auto max-w-xl">
      <PageHeading
        title="Submit an application"
        subtitle="Enter the declared fields and upload the label artwork for review."
      />
      <form onSubmit={onSubmit} className="mt-6 space-y-5 rounded-xl border border-line bg-surface p-6 shadow-sm">
        <Field label="Product type">
          <select name="commodity_type" defaultValue="distilled_spirits" className={inputCls}>
            <option value="distilled_spirits">Distilled spirits</option>
          </select>
        </Field>
        {FIELDS.map((f) => (
          <Field key={f.name} label={f.label}>
            <input name={f.name} required placeholder={f.placeholder} className={inputCls} />
          </Field>
        ))}
        <Field label="Label image">
          <input
            type="file" name="image" accept="image/png,image/jpeg" required
            className="block w-full text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-brand-soft file:px-3 file:py-2 file:text-sm file:font-medium file:text-brand hover:file:brightness-95"
          />
        </Field>
        <button
          disabled={busy}
          className="w-full rounded-md bg-brand px-5 py-3 text-base font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Submitting…" : "Submit for review"}
        </button>
        {error && <p className="text-sm text-fail">Could not submit: {error}</p>}
      </form>
    </div>
  );
}
