import { useRef, useState } from "react";
import { getApplication, previewApplication, submitApplication } from "../api";
import type { Verification } from "../types";
import { VerificationView } from "../VerificationView";
import { Field, PageHeading, VerdictPill, inputCls } from "../ui";

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
    invalidate();
  }

  return (
    <div className="rise mx-auto max-w-6xl">
      <PageHeading
        title="Submit an application"
        subtitle="Drop the label artwork on the left, then enter the declared fields on the right. Combine every panel (front, back, side) into one image."
      />
      <form key={formKey} ref={formRef} onSubmit={onCheck} onChange={invalidate} className="mt-6 grid items-start gap-6 lg:grid-cols-[3fr_2fr]">
        <DropZone />
        <div className="space-y-5 rounded-xl border border-line bg-surface p-6 shadow-sm">
          <Field label="Product type">
            <select name="commodity_type" defaultValue="distilled_spirits" className={inputCls}>
              <option value="distilled_spirits">Distilled spirits</option>
              <option value="wine">Wine</option>
              <option value="malt_beverage">Malt beverage</option>
            </select>
          </Field>
          {FIELDS.map((f) => (
            <Field key={f.name} label={f.label}>
              <input name={f.name} required placeholder={f.placeholder} className={inputCls} />
            </Field>
          ))}
          <button
            disabled={busy}
            className="w-full rounded-md bg-brand px-5 py-3 text-base font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
          >
            {busy && !checked ? "Checking…" : "Check label"}
          </button>
          {error && <p className="text-sm text-fail">Could not check: {error}</p>}
        </div>
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
      className={`flex min-h-[40rem] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition ${
        over ? "border-brand bg-brand-soft" : "border-line bg-surface hover:border-brand/50"
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
          <img src={preview} alt="label preview" className="max-h-[36rem] w-auto rounded-md border border-line shadow-sm" />
          <span className="text-xs text-muted">{fileName} · click or drop to replace</span>
          {multiWarn && (
            <span className="text-xs font-medium text-flag">
              Only the first image was kept — combine all panels into one image and re-drop.
            </span>
          )}
        </>
      ) : (
        <>
          <span aria-hidden className="text-4xl text-muted">⤓</span>
          <span className="font-serif text-lg text-ink">Drop the label artwork here</span>
          <span className="text-sm text-muted">or click to choose a file — flat label image (PNG or JPEG)</span>
          <span className="text-xs text-muted">
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
    <div data-testid="check-feedback" className="rise mt-8 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-serif text-2xl font-semibold text-ink">
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
          className="rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
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
    <div className="rise mt-8 space-y-4 rounded-xl border border-line bg-surface p-6 shadow-sm">
      <h2 className="font-serif text-2xl font-semibold text-ink">Submitted — now in the review queue</h2>
      <p className="text-muted">A TTB reviewer will make the final decision. You can submit another application.</p>
      <button
        type="button"
        onClick={onAgain}
        className="rounded-md bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
      >
        Submit another application
      </button>
    </div>
  );
}
