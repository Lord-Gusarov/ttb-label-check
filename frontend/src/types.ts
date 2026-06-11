export type Verdict = "pass" | "warn" | "needs_review" | "fail";
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
  fields: FieldResult[];
  words: { text: string; bbox: Box }[];
}
export interface AppSummary {
  id: string; brand_name: string; commodity_type: string;
  status: string; created_at: number;
}
export interface AppDetail extends AppSummary {
  class_type: string; alcohol_content: string; net_contents: string;
  decision_note: string | null; verification: Verification | null;
}
