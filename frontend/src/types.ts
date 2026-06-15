export type Verdict = "pass" | "warn" | "needs_review";
export type Box = [number, number, number, number];

export interface FieldResult {
  field: string;
  label: string;
  verdict: Verdict;
  kind: "match" | "present";
  expected: string | null;
  found: string | null;
  detail: string;
  boxes: Box[];
}
export interface Verification {
  overall: Verdict;
  engine: string;
  elapsed_ms: number;
  warning_tier?: number; // 1 = read locally, 2 = model-assisted
  text: string;
  fields: FieldResult[];
  words: { text: string; bbox: Box }[];
}
export interface AppSummary {
  id: string; brand_name: string; commodity_type: string;
  status: string; created_at: number;
  overall?: Verdict | null; // automated recommendation, for queue triage
}
export interface AppDetail extends AppSummary {
  class_type: string; alcohol_content: string; net_contents: string;
  decision_note: string | null; verification: Verification | null;
}
