# GTM Engineering Internship Submission

## Project
**Nexora** - Structured Questionnaire Answering Tool

## Live Application
- App URL: https://nupreeth-nexora.hf.space
- Space URL: https://huggingface.co/spaces/Nupreeth/Nexora

## Code Repository
- GitHub: https://github.com/Nupreeth/Nexora

## What Was Built
Nexora is an end-to-end web application for completing structured questionnaires (security/compliance/vendor forms) using uploaded internal references as source-of-truth.  
It supports authenticated users, document upload, grounded answer generation with citations, reviewer edits, and downloadable exports.

## Assignment Coverage (Must-Haves)
- User authentication (`signup/login/logout`)
- Persistent database-backed storage (`SQLAlchemy`; deployed with external Postgres via `DATABASE_URL`)
- Clear flow: upload -> generate -> review/edit -> export
- AI retrieval and grounded answer generation
- Citation-backed outputs
- Explicit fallback: `"Not found in references."` when unsupported
- Structured review view (`Question`, `Answer`, `Citations`)
- Export preserving questionnaire order/structure (CSV/XLSX/PDF flows)

## Nice-to-Haves Implemented
- Confidence score
- Evidence snippets
- Coverage summary
- Run history (versioned runs)

## Industry & Fictional Company
- Industry: B2B SaaS (Supply Chain / Procurement Operations)
- Fictional company: **CrestPilot Logistics Cloud**

## Demo Steps
1. Open the live app and create an account.
2. Upload questionnaire + reference documents.
3. Click **Generate Answers Now**.
4. Review and edit answers in **Review & Export**.
5. Use follow-up grounded chat in the same run.
6. Export the answered questionnaire document.

## Notes
- Deployment target: Hugging Face Spaces (Docker).
- Persistence configured using external Postgres (`DATABASE_URL`) for durable DB storage.
