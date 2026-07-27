# Proteus

Proteus is a professor-calibrated essay grading application. Its goal is to
reproduce a professor's grading decisions consistently, using the assignment's
rubric, previous professor-scored submissions, and ongoing review feedback.

## Grading workflow

1. Create a course and assignment.
2. Select a built-in rubric or import a rubric as JSON.
3. On the assignment page, add previous graded examples. Each example includes
   the full submission plus the professor's score and rationale for every
   rubric criterion. PDF, DOC, DOCX, and plain-text imports are supported.
4. Submit new student work and grade it. Proteus retrieves only examples from
   the same professor, assignment, rubric, version, and criterion. The prompt
   uses a single professor-calibrated grading path; it does not compare against
   a generic "correct" grader.
5. Review each criterion. Approving a score or overriding it records explicit
   feedback and adds that decision to the assignment's future calibration set.

A separate relevance check warns when a submission appears unrelated to the
assignment prompt. It is advisory: rubric grading still completes.

Historical assessments created by the earlier dual-path engine remain
viewable and are labeled as historical comparisons.

## Run locally

Requirements: Python 3.11 or newer, Node.js, and an LLM provider key or a local
Ollama installation.

```bash
make setup
make seed
make dev
```

Open `http://localhost:5183`. The API runs on `http://localhost:8731`.

Provider settings can be configured in the application or through
`LLM_PROVIDER` and the matching `<PROVIDER>_API_KEY`. Supported providers are
OpenAI, Anthropic, Gemini, Groq, Mistral, GitHub Models, TAMU, and Ollama.

## Verify

```bash
PYTHONPATH=backend backend/.venv/bin/pytest backend/tests
cd frontend && npm run build && npm run lint
```
