"""Assessment grade-report PDF rendering (pure presentation).

Takes a plain report dict (assembled by routers.assessments, which owns the
DB access and reuses _criterion_output) and lays it out with reportlab's
platypus flowables so multi-page essay text and rationales wrap and paginate
automatically. No DB or app imports here on purpose — keeps this a dumb
renderer and avoids a cycle with the router that calls it.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

_ACCENT = colors.HexColor("#2563eb")
_MUTED = colors.HexColor("#6b7280")
_AMBER = colors.HexColor("#b45309")


def _fmt_score(value) -> str:
    """0-5 scores are stored as REAL medians; show whole numbers without a
    trailing .0, fractional medians (e.g. 3.5) as-is, None as 'no-evidence'."""
    if value is None:
        return "no-evidence"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _p(text: str, style) -> Paragraph:
    # Paragraph parses a mini-HTML dialect, so any literal <, >, & in essay or
    # rationale text must be escaped or it raises / drops content.
    return Paragraph(escape(text or ""), style)


def _styles() -> dict:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=6
    )
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontSize=20, leading=24, spaceAfter=2),
        "meta": ParagraphStyle("Meta", parent=body, fontSize=9, textColor=_MUTED, spaceAfter=2),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontSize=13, leading=16, spaceBefore=14, spaceAfter=6),
        "dimension": ParagraphStyle(
            "Dim", parent=base["Heading3"], fontSize=10, leading=13, textColor=_MUTED,
            spaceBefore=10, spaceAfter=4,
        ),
        "criterion": ParagraphStyle("Crit", parent=body, fontSize=11, leading=14, spaceAfter=1, spaceBefore=6),
        "stat": ParagraphStyle("Stat", parent=body, fontSize=9, leading=12, textColor=_ACCENT, spaceAfter=3),
        "flag": ParagraphStyle("Flag", parent=body, fontSize=9, leading=12, textColor=_AMBER, spaceAfter=3),
        "body": body,
        "quote": ParagraphStyle(
            "Quote", parent=body, fontSize=9, leading=12, textColor=_MUTED,
            leftIndent=12, borderPadding=0, spaceAfter=3,
        ),
        "override": ParagraphStyle(
            "Override", parent=body, fontSize=9.5, leading=13, textColor=_ACCENT, leftIndent=6, spaceAfter=4,
        ),
        "essay": ParagraphStyle("Essay", parent=body, fontSize=10, leading=15, spaceAfter=8),
    }


def _criterion_flowables(c: dict, s: dict) -> list:
    # Raw Paragraph (not _p): the <b> tags are intentional markup, so only the
    # dynamic id/statement get escaped, not the whole string.
    out = [Paragraph(f"<b>{escape(c['criterion_id'])}</b> — {escape(c.get('statement') or '')}", s["criterion"])]

    parts = [f"Output score: <b>{_fmt_score(c['output_score'])}</b> ({escape(c['output_source'])})"]
    if c.get("legacy_dual_path"):
        parts.append(f"personalized {_fmt_score(c.get('personalized_score'))}")
        parts.append(f"exemplar {_fmt_score(c.get('exemplar_score'))}")
    elif c.get("personalized_score") is not None:
        parts.append(f"professor-calibrated {_fmt_score(c.get('personalized_score'))}")
    if c.get("score_diff") is not None:
        verdict = "exceeds threshold" if c.get("exceeds_threshold") else "within threshold"
        parts.append(f"divergence Δ{_fmt_score(c['score_diff'])} ({verdict})")
    out.append(Paragraph(" &nbsp;·&nbsp; ".join(parts), s["stat"]))

    reasons = c.get("review_reasons") or []
    if reasons:
        out.append(_p("Flagged: " + ", ".join(r.replace("_", " ") for r in reasons), s["flag"]))

    if c.get("rationale"):
        out.append(_p(c["rationale"], s["body"]))

    for e in c.get("evidence") or []:
        quote = e.get("quote", "")
        reasoning = e.get("reasoning", "")
        out.append(_p(f"“{quote}” — {reasoning}", s["quote"]))

    override = c.get("override")
    if override:
        out.append(
            _p(
                f"Instructor override → {_fmt_score(override['new_score'])}: {override.get('new_rationale') or ''}",
                s["override"],
            )
        )
    return out


def build_assessment_pdf(report: dict) -> bytes:
    """Render an assembled report dict to PDF bytes."""
    s = _styles()
    story: list = []

    story.append(_p(report.get("title") or "Grade Report", s["title"]))

    meta_bits = [
        report.get("assignment_name") or "",
        report.get("student_name") or "",
        report.get("external_ref") and f"ref {report['external_ref']}",
        report.get("rubric"),
        report.get("created_at"),
    ]
    story.append(_p(" · ".join(b for b in meta_bits if b), s["meta"]))
    engine_bits = [
        f"status: {report.get('status', '?')}",
        f"model: {report.get('provider', '?')}/{report.get('model', '?')}",
    ]
    if report.get("avg_score") is not None:
        engine_bits.insert(0, f"average output score: {report['avg_score']:.2f} (n={report.get('n_criteria', 0)})")
    story.append(_p(" · ".join(engine_bits), s["meta"]))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#e5e7eb")))

    story.append(_p("Original essay", s["h2"]))
    essay = report.get("essay_text") or ""
    # Preserve paragraph breaks; each blank-line-delimited block is its own
    # flowable so long essays paginate cleanly.
    blocks = [b.strip() for b in essay.replace("\r\n", "\n").split("\n\n")]
    for block in blocks:
        if block:
            story.append(_p(block.replace("\n", " "), s["essay"]))

    story.append(_p("Results by criterion", s["h2"]))
    for dim in report.get("dimensions") or []:
        if dim.get("dimension"):
            story.append(_p(dim["dimension"], s["dimension"]))
        items = [ListItem(_criterion_flowables(c, s), leftIndent=6) for c in dim.get("criteria", [])]
        if items:
            story.append(ListFlowable(items, bulletType="bullet", start="", leftIndent=8, spaceBefore=2))

    buf = BytesIO()
    SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch, topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title=report.get("title") or "Grade Report",
    ).build(story)
    return buf.getvalue()
