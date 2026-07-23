export interface LoginResponse {
  token: string;
  role: "admin" | "instructor";
  instructor_id: string | null;
  theme_preference: "system" | "light" | "dark";
}

export interface Account {
  id: string;
  username: string;
  role: "admin" | "instructor";
  instructor_id: string | null;
  is_active: boolean;
  created_at: string;
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

export interface FlaggedEssay {
  essay_id: string;
  assessment_id: string;
  student_id: string | null;
  exceeds_threshold: boolean;
  high_spread: boolean;
  review_reasons: string[];
}

export interface CriterionBreakdown {
  criterion_id: string;
  n_graded: number;
  avg_score: number;
  min_score: number;
  max_score: number;
  n_divergent: number;
  n_high_spread: number;
  n_weak_referenceability: number;
  n_unsupported_evidence: number;
  flagged: FlaggedEssay[];
}

export interface AssignmentBreakdown {
  n_essays: number;
  n_graded_essays: number;
  criteria: CriterionBreakdown[];
}

export interface StudentHistoryEntry {
  essay_id: string;
  assignment_id: string;
  assignment_name: string;
  created_at: string;
  assessment_id: string | null;
  status: "running" | "pending" | "complete" | "failed" | "cancelled" | null;
  avg_score: number | null;
  n_criteria: number;
  n_divergent: number;
  n_high_spread: number;
  needs_review: boolean;
}

export interface StudentHistory {
  student: { id: string; display_name: string; external_ref: string | null; status: string };
  history: StudentHistoryEntry[];
}

export interface QueueEntry {
  essay_id: string;
  student_id: string | null;
  latest_assessment_id: string | null;
  status: "running" | "pending" | "complete" | "failed" | "cancelled" | null;
  exceeds_threshold: boolean;
  high_spread: boolean;
  needs_review: boolean;
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

export interface PersonalizedExcerpt {
  id: string;
  rubric_id: string;
  criterion_id: string;
  instructor_id: string;
  course_id: string | null;
  assignment_id: string | null;
  excerpt_text: string;
  score: number;
  anchor_matched: number;
  rationale: string;
  source: string;
  added_by: string;
  created_at: string;
  updated_at: string;
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
  // Soft flag (B3) — output_score above is unaffected by this; it's purely
  // "an instructor should look at this," never a block on grading.
  needs_review: boolean;
  review_reasons: string[];
}

export interface AssessmentDetail {
  id: string;
  status: string;
  rubric_id: string;
  rubric_version: string;
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
  // Renamed from "confidence" (B2): 1 - spread/5 across N passes — a
  // stability heuristic, not a probability the score is correct. Only
  // meaningful when n_passes > 1.
  pass_stability: number;
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
  criterion: { statement: string; anchors: Record<string, string> } | null;
  personalized: PathResult | null;
  exemplar: PathResult | null;
  divergence: Divergence | null;
  current_override: Override | null;
}
