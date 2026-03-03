---
title: Nexora
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Nexora

Production-style structured questionnaire answering platform for B2B SaaS security/compliance workflows.

## Quick Links
- Live App: https://nupreeth-nexora.hf.space
- GitHub Repository: https://github.com/Nupreeth/Nexora

## 1. What Was Built
Nexora is a full-stack web application that automates structured questionnaire completion using uploaded reference documents as the source of truth.

Core capabilities:
- User authentication (`Sign up`, `Login`, `Logout`)
- Signup safety check with `confirm password` validation
- Persistent data storage with SQLAlchemy (`SQLite` local, `PostgreSQL` compatible via `DATABASE_URL`)
- Questionnaire upload and parsing (CSV, XLSX, PDF, TXT)
- Reference document upload and ingestion (TXT, MD, PDF, DOCX, CSV, XLSX)
- AI-assisted answer generation using retrieval over reference chunks
- Citation attachment for every supported answer
- `"Not found in references."` fallback for unsupported questions
- Reviewer edit workflow before export
- Document export preserving original questionnaire order/structure
- Same-format export support for CSV/XLSX/PDF questionnaire inputs
- Grounded assistant chat (GPT-style) over uploaded references with persistent chat history
- Run-scoped follow-up chat in review page (defaults to run references, optional checkbox to include full library)

## 2. Industry & Fictional Company (Required Context)
- Industry: B2B SaaS for supply chain and procurement operations
- Fictional company: **CrestPilot Logistics Cloud**

CrestPilot Logistics Cloud helps manufacturers and distributors manage vendor onboarding, shipment orchestration, and supplier analytics.  
It serves mid-market and enterprise customers in North America, and frequently responds to customer security/compliance questionnaires.

Files:
- Company profile: `sample_data/company_profile.md`
- Questionnaire (12 questions): `sample_data/questionnaire.csv`
- References (6 docs): `sample_data/references/*`

## 3. Assignment Requirement Mapping
### Must-have requirements
1. User authentication: implemented via `Flask-Login` and hashed passwords.
2. Persistent DB: implemented via SQLAlchemy models with local SQLite and production-ready external PostgreSQL support.
3. Upload -> generate -> review -> export flow: fully implemented.
4. AI meaningful work: retrieval + extractive answer composition over chunked reference corpus.
5. Grounded outputs with citations: each supported answer includes citations + evidence snippets.
6. Unsupported answers: strict fallback to `"Not found in references."`.
7. Output document with same questionnaire structure/order: export preserves original order and adds answer columns for spreadsheet inputs.
   PDF inputs are exported as answered PDFs with questions unchanged and answers/citations inserted below each question.

### Nice-to-have implemented
1. Confidence score per answer.
2. Evidence snippets shown in review UI.
3. Coverage summary (total, cited, not found).
4. Version history through run tracking (`GenerationRun` entries).
5. Persistent grounded chat sessions (`ChatSession` + `ChatMessage`).

## 4. System Architecture
```
run.py / wsgi.py
app/
  __init__.py            # app factory, extension setup, blueprints, error handlers
  config.py              # env-driven configuration
  extensions.py          # db + login manager
  models.py              # domain models
  routes/
    auth.py              # signup/login/logout
    workflow.py          # dashboard, upload, generate, review, export, assistant chat
  services/
    parser_service.py    # file parsing for questionnaire + references
    retrieval_service.py # chunking, tf-idf retrieval, grounded answer creation
    export_service.py    # export to csv/xlsx/txt preserving structure/order
  templates/
  static/css/
tests/
sample_data/
```

## 5. AI Answering Approach
For each generation run:
1. Parse questionnaire into ordered questions.
2. Parse references into plain text.
3. Chunk reference text into bounded sections.
4. Build TF-IDF vector index over chunks.
5. Retrieve top-k relevant chunks per question by cosine similarity.
6. Generate extractive answer from highest relevance sentences.
7. Attach citations and evidence snippets.
8. If relevance threshold is not met: return `"Not found in references."`.

This keeps outputs grounded and auditable without hallucinating unsupported claims.

## 6. Local Setup
### Prerequisites
- Python 3.10+ (3.11 recommended)

### Create and activate virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies
```powershell
pip install -r requirements.txt
```

### Run app
```powershell
python run.py
```

App URL: `http://127.0.0.1:5000`

## 7. How to Demo Quickly
1. Sign up a user account.
2. Upload `sample_data/questionnaire.csv`.
3. Upload all files from `sample_data/references/`.
4. Click `Generate Answers Now` (smooth run flow).
5. Review, edit if needed, and export.

## 8. Testing
Run unit tests:
```powershell
pytest
```

Current test scope:
- Questionnaire parsing behavior
- Retrieval grounding / not-found fallback behavior
- Spreadsheet export integrity

## 9. Assumptions
- Questionnaire files are mostly structured and contain identifiable question rows.
- Spreadsheet export preserving row order + adding answer columns is acceptable structure preservation.
- For unsupported/weakly supported questions, strict not-found behavior is preferred over speculative answers.

## 10. Trade-offs
- Uses TF-IDF retrieval for deterministic local execution and no external LLM dependency.
- SQLite is used for portability; production would typically use PostgreSQL.
- DB schema is created with `db.create_all()` for simplicity; production should use migrations.
- Authentication is session-based with local user store; enterprise SSO is not included.

## 11. Improvements With More Time
1. LLM augmentation (optional) with citation-grounded generation guardrails.
2. Pixel-perfect PDF layout parity with original questionnaire templates.
3. Role-based access control and organization-level workspaces.
4. Background job queue for large document processing.
5. Audit trail with per-field edit history.
6. Vector database backend for scale.

## 12. Deployment Notes
Included:
- `Dockerfile`
- `Procfile`
- `wsgi.py` (Gunicorn entrypoint)

Suggested hosts:
- Render
- Railway
- Fly.io

Set env vars in deployment:
- `SECRET_KEY`
- `DATABASE_URL`

Recommended for durable persistence:
- Use managed Postgres (Neon/Supabase/Render Postgres) and set `DATABASE_URL` to that value.
- App accepts `postgres://...` and `postgresql://...` URLs and normalizes them automatically.
- Avoid relying on container-local SQLite in free serverless/container environments for long-term persistence.
- Current deployment is configured to use external Postgres via `DATABASE_URL` (Neon).

## 13. Best No-Card Deployment
If you need deployment without a credit card, use Hugging Face Spaces (Docker):
- See: `DEPLOY_HF_SPACES.md`

## 14. Final Submission Checklist
- [x] User authentication
- [x] Persistent database-backed models
- [x] Upload questionnaire + references
- [x] Parse questions from uploaded file
- [x] Retrieve evidence from references
- [x] Generate grounded answers with citations
- [x] Return `"Not found in references."` when unsupported
- [x] Structured review UI with question/answer/citations
- [x] Reviewer edits before export
- [x] Export preserves question order and adds answers/citations
- [x] Nice-to-have: confidence score
- [x] Nice-to-have: evidence snippets
- [x] Nice-to-have: coverage summary
- [x] Nice-to-have: run history
