import type { AppDetail, AppSummary, Verification } from "./types";

/** Verify a label WITHOUT persisting it — the submit-time self-check. */
export async function previewApplication(form: FormData): Promise<Verification> {
  const r = await fetch("/api/applications/preview", { method: "POST", body: form });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  return r.json();
}
export async function submitApplication(form: FormData): Promise<{ id: string }> {
  const r = await fetch("/api/applications", { method: "POST", body: form });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  return r.json();
}
export async function listApplications(): Promise<AppSummary[]> {
  const r = await fetch("/api/applications");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function getApplication(id: string): Promise<AppDetail> {
  const r = await fetch(`/api/applications/${id}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function decide(id: string, decision: string, note: string): Promise<AppDetail> {
  const r = await fetch(`/api/applications/${id}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
export async function reverify(id: string): Promise<AppDetail> {
  const r = await fetch(`/api/applications/${id}/reverify`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
