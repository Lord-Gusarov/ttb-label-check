import type { AppDetail, AppSummary, Verification } from "./types";

/** Parse a response, surfacing the backend's `detail` message on any non-OK status. */
async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  return r.json();
}

/** Verify a label WITHOUT persisting it — the submit-time self-check. */
export async function previewApplication(form: FormData): Promise<Verification> {
  return json(await fetch("/api/applications/preview", { method: "POST", body: form }));
}
export async function submitApplication(form: FormData): Promise<{ id: string }> {
  return json(await fetch("/api/applications", { method: "POST", body: form }));
}
export async function listApplications(): Promise<AppSummary[]> {
  return json(await fetch("/api/applications"));
}
export async function getApplication(id: string): Promise<AppDetail> {
  return json(await fetch(`/api/applications/${id}`));
}
export async function decide(id: string, decision: string, note: string): Promise<AppDetail> {
  return json(await fetch(`/api/applications/${id}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  }));
}
export async function reverify(id: string): Promise<AppDetail> {
  return json(await fetch(`/api/applications/${id}/reverify`, { method: "POST" }));
}
