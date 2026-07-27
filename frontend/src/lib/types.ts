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

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_username: string | null;
  actor_role: string | null;
  instructor_id: string | null;
  action: string;
  outcome: "success" | "failure" | "denied";
  target_type: string | null;
  target_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown>;
}

export interface AuditEventPage {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
  actions: string[];
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
  relevance_decision: RelevanceDecision | null;
}

export interface StudentHistory {
  student: {
    id: string;
    course_id: string | null;
    display_name: string;
    external_ref: string | null;
    status: string;
  };
  history: StudentHistoryEntry[];
}

export type RelevanceDecision = "grade" | "reject" | "manual_review";

export interface QueueEntry {
  essay_id: string;
  student_id: string | null;
  latest_assessment_id: string | null;
  status: "running" | "pending" | "complete" | "failed" | "cancelled" | null;
  exceeds_threshold: boolean;
  high_spread: boolean;
  needs_review: boolean;
  relevance_decision: RelevanceDecision | null;
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
  assignmentGuidance?: string | null;
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

export interface CalibrationExampleScore {
  criterion_id: string;
  score: number;
  rationale: string;
}

export interface CalibrationExample {
  id: string;
  name: string;
  source: "uploaded" | "review_approved" | "review_override";
  source_assessment_id: string | null;
  character_count: number;
  text_preview: string;
  created_at: string;
  updated_at: string;
  scores: CalibrationExampleScore[];
}

export interface CalibrationCoverage {
  criterion_id: string;
  n_examples: number;
  scores_present: number[];
  ready: boolean;
}

export interface CalibrationSummary {
  examples: CalibrationExample[];
  n_examples: number;
  criteria: CalibrationCoverage[];
  ready: boolean;
  minimum_recommended_examples: number;
  feedback: {
    n_reviewed: number;
    n_approved: number;
    n_overridden: number;
    acceptance_rate: number | null;
    mean_abs_adjustment: number | null;
  };
}

export interface AssessmentCriterionSummary {
  criterion_id: string;
  output_score: number | null;
  // "incomplete": the criterion has no calibrated aggregate (grading failed
  // partway through it) — no output grade exists for it.
  output_source: "override" | "calibrated" | "personalized" | "incomplete";
  exceeds_threshold: boolean;
  // High spread: this calibrated run's N sampling passes disagreed.
  // exceeds_threshold is retained for historical dual-path results only.
  high_spread: boolean;
  // Soft flag (B3) — output_score above is unaffected by this; it's purely
  // "an instructor should look at this," never a block on grading.
  needs_review: boolean;
  review_reasons: string[];
}

export interface AssessmentDetail {
  id: string;
  assignment_id: string;
  status: string;
  rubric_id: string;
  rubric_version: string;
  relevance_check: RelevanceCheck | null;
  criteria: AssessmentCriterionSummary[];
}

export interface Evidence {
  quote: string;
  reasoning: string;
}

export interface RelevanceCheck {
  decision: RelevanceDecision;
  submission_type: "student_response" | "instructions" | "rubric" | "source_material" | "other";
  responds_to_prompt: boolean;
  has_sufficient_content: boolean;
  rationale: string;
  evidence: Evidence[];
  created_at: string;
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
  calibrated: PathResult | null;
  personalized: PathResult | null;
  exemplar: PathResult | null;
  legacy_dual_path: boolean;
  divergence: Divergence | null;
  current_override: Override | null;
  professor_feedback: {
    action: "approved" | "overridden";
    model_score: number | null;
    professor_score: number;
    professor_rationale: string;
    updated_at: string;
  } | null;
}
