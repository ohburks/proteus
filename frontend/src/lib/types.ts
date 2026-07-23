export interface LoginResponse {
  token: string;
  role: "admin" | "instructor";
  instructor_id: string | null;
  theme_preference: "system" | "light" | "dark";
}

export interface Course {
  id: string;
  instructor_id: string;
  name: string;
}

export interface Assignment {
  id: string;
  course_id: string;
  name: string;
  rubric_id: string;
  rubric_version: string;
}

export interface Student {
  id: string;
  instructor_id: string;
  course_id: string | null;
  display_name: string;
  external_ref: string | null;
  status: string;
}

export interface Essay {
  id: string;
  assignment_id: string;
  student_id: string | null;
  text: string;
}

export interface QueueEntry {
  essay_id: string;
  student_id: string | null;
  latest_assessment_id: string | null;
  status: "running" | "pending" | "complete" | "failed" | null;
  exceeds_threshold: boolean;
  high_spread: boolean;
}

export interface RubricCriterion {
  criterionId: string;
  standard: string;
  dimension: string;
  statement: string;
  scale: string;
  referenceability: "strong" | "weak";
  anchors: Record<string, string>;
}

export interface Rubric {
  rubricId: string;
  version: string;
  genre: string;
  notes: string;
  criteria: RubricCriterion[];
}

export interface AssessmentCriterionSummary {
  criterion_id: string;
  output_score: number | null;
  // "incomplete": the criterion has no personalized aggregate (grading failed
  // partway through it) — no output grade exists for it.
  output_source: "override" | "personalized" | "incomplete";
  exceeds_threshold: boolean;
  // High spread: this path's own N sampling passes disagreed with each other.
  // Distinct from exceeds_threshold (divergence BETWEEN the two paths) —
  // never merge these two signals.
  high_spread: boolean;
}

export interface AssessmentDetail {
  id: string;
  status: string;
  criteria: AssessmentCriterionSummary[];
}

export interface Evidence {
  quote: string;
  reasoning: string;
}

export interface RawPass {
  pass_index: number;
  score: number | "no-evidence";
  anchor_matched: number;
  evidence: Evidence[];
  rationale: string;
  confidence: number; // this pass's own raw self-reported confidence
}

export interface PathResult {
  score: number | "no-evidence"; // median across this path's N sampling passes
  anchor_matched: number;
  evidence: Evidence[];
  rationale: string;
  precedent_ids: string[];
  // Multi-pass summary (design doc §7 multi-pass extension):
  spread: number | null; // disagreement WITHIN this path's own repeated passes
  confidence: number; // spread-derived heuristic — lower spread means higher confidence
  high_spread: boolean; // spread exceeds this criterion's spread threshold
  n_passes: number;
  passes: RawPass[]; // every raw pass, kept for audit
}

export interface Divergence {
  score_diff: number | null;
  anchor_mismatch: boolean;
  no_evidence_asymmetry: boolean;
  exceeds_threshold: boolean;
}

export interface Override {
  new_score: number;
  new_rationale: string;
  overridden_by: string;
  created_at: string;
}

export interface ReviewContract {
  criterion_id: string;
  personalized: PathResult | null;
  exemplar: PathResult | null;
  divergence: Divergence | null;
  current_override: Override | null;
}
