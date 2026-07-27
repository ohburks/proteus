from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

# A non-empty string after trimming surrounding whitespace — rejects "" and
# "   " with a 422 rather than persisting a blank course/assignment/essay.
NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortNonBlankStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
RubricTextStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    instructor_id: str | None
    theme_preference: str


class AccountCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "instructor"]


class AccountStatusUpdate(BaseModel):
    is_active: bool


class CourseCreate(BaseModel):
    name: NonBlankStr


class CourseOut(BaseModel):
    id: str
    instructor_id: str
    name: str


class AssignmentCreate(BaseModel):
    course_id: str
    name: NonBlankStr
    rubric_id: str
    rubric_version: str
    prompt_text: str | None = None
    format_expectations: str | None = None
    criterion_emphasis_notes: str | None = None
    common_pitfalls: str | None = None


class AssignmentOut(BaseModel):
    id: str
    course_id: str
    name: str
    rubric_id: str
    rubric_version: str


class StudentCreate(BaseModel):
    course_id: str | None = None
    display_name: NonBlankStr
    external_ref: str | None = None


class StudentOut(BaseModel):
    id: str
    instructor_id: str
    course_id: str | None
    display_name: str
    external_ref: str | None
    status: str


class StudentUpdate(BaseModel):
    external_ref: str | None = None
    status: Literal["active", "archived"]


class EssayCreate(BaseModel):
    assignment_id: str
    student_id: str | None = None
    text: NonBlankStr


class EssayOut(BaseModel):
    id: str
    assignment_id: str
    student_id: str | None
    text: str


class BYOKConfig(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class GradeRequest(BaseModel):
    essay_id: str
    byok: BYOKConfig | None = None


class BulkGradeRequest(BaseModel):
    essay_ids: list[str]
    byok: BYOKConfig | None = None


class AssessmentOut(BaseModel):
    id: str
    essay_id: str
    status: str
    provider: str
    model: str


class InstructorProfileUpdate(BaseModel):
    grading_philosophy: str | None = None
    deprioritized_criteria: list[str] | None = None
    prioritized_criteria: list[str] | None = None
    rationale_tone: str | None = None
    default_llm_provider: str | None = None
    default_llm_model: str | None = None


class CourseProfileUpdate(BaseModel):
    cohort_level: str | None = None
    curriculum_texts: list[str] | None = None
    rubric_version_pin: str | None = None


class AssignmentProfileUpdate(BaseModel):
    prompt_text: str | None = None
    format_expectations: str | None = None
    criterion_emphasis_notes: str | None = None
    common_pitfalls: str | None = None


class DivergenceThresholdUpdate(BaseModel):
    rubric_id: str
    criterion_id: str
    threshold: int = Field(ge=0, le=5)


class PoolThresholdUpdate(BaseModel):
    rubric_id: str
    criterion_id: str | None = None
    min_scoped_pool_size: int = Field(gt=0, le=20)


class SpreadThresholdUpdate(BaseModel):
    rubric_id: str
    criterion_id: str
    threshold: float = Field(ge=0, le=5)


class ThemeUpdate(BaseModel):
    theme_preference: str


class OverrideRequest(BaseModel):
    new_score: int = Field(ge=0, le=5)
    new_rationale: str = Field(min_length=1)


class AdoptExemplarRequest(BaseModel):
    pass


class PersonalizedExcerptCreate(BaseModel):
    rubric_id: str
    criterion_id: str
    course_id: str | None = None
    assignment_id: str | None = None
    excerpt_text: str
    score: int = Field(ge=0, le=5)
    anchor_matched: int = Field(ge=0, le=5)
    rationale: str
    source_essay_text: str


class CalibrationCriterionScore(BaseModel):
    criterion_id: ShortNonBlankStr
    score: int = Field(ge=0, le=5)
    rationale: RubricTextStr


class CalibrationExampleCreate(BaseModel):
    name: ShortNonBlankStr
    essay_text: str = Field(min_length=1, max_length=50_000)
    scores: list[CalibrationCriterionScore] = Field(min_length=1, max_length=100)

    @field_validator("essay_text")
    @classmethod
    def essay_must_have_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("essay_text must contain non-whitespace text")
        return value

    @model_validator(mode="after")
    def score_ids_must_be_unique(self):
        ids = [item.criterion_id for item in self.scores]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion_id values must be unique")
        return self


class RubricCriterionImport(BaseModel):
    criterionId: ShortNonBlankStr
    standard: str | None = Field(default=None, max_length=500)
    dimension: ShortNonBlankStr
    statement: RubricTextStr
    scale: str = Field(default="0-5", max_length=20)
    referenceability: Literal["strong", "weak"] = "strong"
    source: str | None = Field(default=None, max_length=500)
    anchors: dict[str, RubricTextStr]

    @field_validator("anchors")
    @classmethod
    def anchors_cover_scale(cls, value: dict[str, str]) -> dict[str, str]:
        expected = {str(score) for score in range(6)}
        missing = sorted(expected - set(value))
        if missing:
            raise ValueError(f"anchors must include scores 0-5; missing {', '.join(missing)}")
        unexpected = sorted(set(value) - expected)
        if unexpected:
            raise ValueError(
                f"anchors may contain only scores 0-5; unexpected {', '.join(unexpected)}"
            )
        return value


class RubricImport(BaseModel):
    rubricId: ShortNonBlankStr
    version: ShortNonBlankStr
    genre: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)
    assignmentGuidance: str | None = Field(default=None, max_length=10_000)
    criteria: list[RubricCriterionImport] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def criterion_ids_must_be_unique(self):
        ids = [item.criterionId for item in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterionId values must be unique")
        return self
