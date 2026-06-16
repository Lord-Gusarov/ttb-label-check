import { useRef, useState } from "react";
import { getApplication, previewApplication, submitApplication } from "../api";
import type { Verification } from "../types";
import { VerificationView } from "../VerificationView";
import { Card, Field, PageHeading, VerdictPill, btnPrimary, inputCls } from "../ui";

const FIELDS = [
  { name: "brand_name", label: "Brand name", placeholder: "OLD TOM DISTILLERY" },
  { name: "class_type", label: "Class / type designation", placeholder: "Kentucky Straight Bourbon Whiskey" },
  { name: "alcohol_content", label: "Alcohol content", placeholder: "45% Alc./Vol. (90 Proof)" },
  { name: "net_contents", label: "Net contents", placeholder: "750 mL" },
];

export function SubmitPage() {
  const formRef = useRef<HTMLFormElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Verification | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [formKey, setFormKey] = useState(0); // bump to remount the form subtree (full reset)
  const [source, setSource] = useState("domestic"); // gates the country-of-origin field

  // Any edit after a check invalidates it — you can never submit data that wasn't checked.
  function invalidate() {
    setError(null);
    setSubmitted(false);
    setChecked(null);
    setImageUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
  }

  async function onCheck(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const verification = await previewApplication(fd);
      const file = fd.get("image");
      setImageUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return file instanceof File ? URL.createObjectURL(file) : null;
      });
      setChecked(verification);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    const form = formRef.current;
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const { id } = await submitApplication(new FormData(form));
      // Warm the persisted app's verification so the agent queue can triage it immediately
      // (the queue groups by the cached verdict; without this it would arrive ungrouped).
      await getApplication(id);
      setSubmitted(true);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function onAgain() {
    setFormKey((k) => k + 1); // remount the form -> clears inputs AND the DropZone preview state
    setSource("domestic");
    invalidate();
  }

  return (
    <div className="rise mx-auto max-w-6xl">
      <PageHeading
        title="Submit an application"
        subtitle="Drop the label artwork on the left, then enter the declared fields on the right. Combine every panel (front, back, side) into one image."
      />
      <form key={formKey} ref={formRef} onSubmit={onCheck} onChange={invalidate} className="mt-8 grid items-start gap-6 lg:grid-cols-[3fr_2fr]">
        <DropZone />
        <Card className="space-y-5 p-6">
          <Field label="Product type">
            <select name="commodity_type" defaultValue="distilled_spirits" className={inputCls}>
              <option value="distilled_spirits">Distilled spirits</option>
              <option value="wine">Wine</option>
              <option value="malt_beverage">Malt beverage</option>
            </select>
          </Field>
          <Field label="Source">
            <select name="source" value={source} onChange={(e) => setSource(e.currentTarget.value)} className={inputCls}>
              <option value="domestic">Domestic</option>
              <option value="imported">Imported</option>
            </select>
          </Field>
          {source === "imported" && (
            <Field label="Country of origin">
              <input name="country_of_origin" placeholder="France" className={inputCls} />
            </Field>
          )}
          {FIELDS.map((f) => (
            <Field key={f.name} label={f.label}>
              <input name={f.name} required placeholder={f.placeholder} className={inputCls} />
            </Field>
          ))}
          <Field label="Name & address of bottler/producer">
            <input
              name="responsible_party"
              placeholder="Bottled by ACME Distillery, City, ST"
              className={inputCls}
            />
          </Field>
          <button disabled={busy} className={`${btnPrimary} w-full px-5 py-3 text-base`}>
            {busy && !checked ? "Checking…" : "Check label"}
          </button>
          {error && <p role="alert" className="text-sm font-medium text-fail">Could not check: {error}</p>}
        </Card>
      </form>

      {submitted ? (
        <SubmittedBanner onAgain={onAgain} />
      ) : (
        checked && <CheckFeedback verification={checked} imageUrl={imageUrl} busy={busy} onConfirm={onConfirm} />
      )}
    </div>
  );
}

/** Left column: a drag-and-drop zone for the label artwork, with a live preview. The
 *  hidden <input name="image"> lives inside it so the native form's FormData picks it up;
 *  a drop feeds the file into that input via DataTransfer. */
function DropZone() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [multiWarn, setMultiWarn] = useState(false);

  function take(file: File | undefined | null) {
    if (!file) return;
    setFileName(file.name);
    setPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setOver(false);
    // Only one image per application: a multi-file drop (someone dropping front/back/side
    // separately) would otherwise silently keep just the first. Warn instead.
    setMultiWarn((e.dataTransfer.files?.length ?? 0) > 1);
    const file = e.dataTransfer.files?.[0];
    if (file && inputRef.current) {
      const dt = new DataTransfer();
      dt.items.add(file);
      inputRef.current.files = dt.files; // so FormData captures the dropped file
      take(file);
    }
  }

  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`flex min-h-[40rem] cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed p-6 text-center shadow-card transition ${
        over ? "scale-[0.99] border-brand bg-brand-soft" : "border-line-strong bg-surface hover:border-brand/60 hover:bg-brand-soft/40"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        name="image"
        accept="image/png,image/jpeg"
        required
        onChange={(e) => { setMultiWarn(false); take(e.currentTarget.files?.[0]); }}
        className="sr-only"
      />
      {preview ? (
        <>
          <img src={preview} alt="label preview" className="max-h-[36rem] w-auto rounded-xl border border-line shadow-lift" />
          <span className="text-xs text-muted">{fileName} · click or drop to replace</span>
          {multiWarn && (
            <span className="text-xs font-semibold text-flag">
              Only the first image was kept — combine all panels into one image and re-drop.
            </span>
          )}
        </>
      ) : (
        <>
          <span aria-hidden className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand">
            <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 16V4m0 12-4-4m4 4 4-4" />
              <path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2" />
            </svg>
          </span>
          <span className="font-serif text-xl text-ink">Drop the label artwork here</span>
          <span className="text-sm text-muted">or click to choose a file — flat label image (PNG or JPEG)</span>
          <span className="max-w-sm text-xs leading-relaxed text-faint">
            One image per application. If the label has multiple panels (front, back, side),
            combine them into a single image before uploading.
          </span>
        </>
      )}
    </label>
  );
}

/** Inline feedback after a check: the verdict + per-field evidence, then the confirm action.
 *  A PASS offers "Submit"; anything flagged offers "Submit anyway" (a TTB reviewer decides). */
function CheckFeedback({
  verification,
  imageUrl,
  busy,
  onConfirm,
}: {
  verification: Verification;
  imageUrl: string | null;
  busy: boolean;
  onConfirm: () => void;
}) {
  const pass = verification.overall === "pass";
  return (
    <div data-testid="check-feedback" className="rise mt-10 space-y-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-8">
        <h2 className="font-serif text-2xl font-semibold tracking-tight text-ink">
          {pass ? "Looks good — ready to submit" : "Review these before submitting"}
        </h2>
        <VerdictPill verdict={verification.overall} />
      </div>

      <VerificationView verification={verification} imageSrc={imageUrl ?? ""} />

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={onConfirm}
          className={`${btnPrimary} px-5 py-2.5 text-sm`}
        >
          {busy ? "Submitting…" : pass ? "Submit" : "Submit anyway"}
        </button>
        {!pass && (
          <span className="text-sm text-muted">
            Edit a field and check again, or submit anyway — a TTB reviewer makes the final decision.
          </span>
        )}
      </div>
    </div>
  );
}

/** Shown after the submitter confirms: the application is now in the agent queue. */
function SubmittedBanner({ onAgain }: { onAgain: () => void }) {
  return (
    <Card className="rise mt-10 space-y-4 p-8" >
      <div className="flex items-center gap-3">
        <span aria-hidden className="grid h-10 w-10 place-items-center rounded-full bg-pass-soft text-pass">
          <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 12.5 4 4 10-10" />
          </svg>
        </span>
        <h2 className="font-serif text-2xl font-semibold tracking-tight text-ink">Submitted — now in the review queue</h2>
      </div>
      <p className="text-muted">A TTB reviewer will make the final decision. You can submit another application.</p>
      <button type="button" onClick={onAgain} className={`${btnPrimary} px-5 py-2.5 text-sm`}>
        Submit another application
      </button>
    </Card>
  );
}
