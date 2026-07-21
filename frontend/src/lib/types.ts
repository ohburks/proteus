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
  output_source: "override" | "personalized";
  exceeds_threshold: boolean;
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

export interface PathResult {
  score: number | "no-evidence";
  anchor_matched: number;
  evidence: Evidence[];
  rationale: string;
  precedent_ids: string[];
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
