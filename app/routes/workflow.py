import io
import json
import re
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import Answer, GenerationRun, Question, Questionnaire, ReferenceDocument
from ..services.export_service import build_export_payload
from ..services.parser_service import extract_reference_text, parse_questionnaire
from ..services.retrieval_service import answer_question, build_retrieval_index, chunk_references


workflow_bp = Blueprint("workflow", __name__)

ALLOWED_QUESTIONNAIRE_EXTENSIONS = {".csv", ".xlsx", ".pdf", ".txt"}
ALLOWED_REFERENCE_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx"}


@workflow_bp.route("/")
def root():
    if current_user.is_authenticated:
        return redirect(url_for("workflow.dashboard"))
    return redirect(url_for("auth.login"))


@workflow_bp.route("/dashboard")
@login_required
def dashboard():
    questionnaires = (
        Questionnaire.query.filter_by(user_id=current_user.id)
        .order_by(Questionnaire.created_at.desc())
        .all()
    )
    references = (
        ReferenceDocument.query.filter_by(user_id=current_user.id)
        .order_by(ReferenceDocument.created_at.desc())
        .all()
    )
    return render_template(
        "workflow/dashboard.html",
        questionnaires=questionnaires,
        references=references,
    )


@workflow_bp.route("/references/upload", methods=["POST"])
@login_required
def upload_references():
    uploaded_files = request.files.getlist("reference_files")
    if not uploaded_files:
        flash("Please choose one or more reference files.", "error")
        return redirect(url_for("workflow.dashboard"))

    added_count = 0
    for uploaded in uploaded_files:
        original_filename = secure_filename(uploaded.filename or "")
        if not original_filename:
            continue

        ext = Path(original_filename).suffix.lower()
        if ext not in ALLOWED_REFERENCE_EXTENSIONS:
            flash(f"Skipped {original_filename}: unsupported file format.", "error")
            continue

        stored_name = f"{uuid4().hex}{ext}"
        stored_path = current_app.config["REFERENCE_DIR"] / stored_name
        uploaded.save(stored_path)

        try:
            text_content = extract_reference_text(stored_path, ext)
        except Exception:
            stored_path.unlink(missing_ok=True)
            flash(f"Skipped {original_filename}: failed to parse.", "error")
            continue

        if not text_content.strip():
            stored_path.unlink(missing_ok=True)
            flash(f"Skipped {original_filename}: no readable content.", "error")
            continue

        doc = ReferenceDocument(
            user_id=current_user.id,
            original_filename=original_filename,
            stored_path=str(stored_path),
            file_ext=ext,
            text_content=text_content,
        )
        db.session.add(doc)
        added_count += 1

    if added_count:
        db.session.commit()
        flash(f"Uploaded {added_count} reference document(s).", "success")
    else:
        db.session.rollback()
    return redirect(url_for("workflow.dashboard"))


@workflow_bp.route("/questionnaires/upload", methods=["POST"])
@login_required
def upload_questionnaire():
    uploaded = request.files.get("questionnaire_file")
    if not uploaded:
        flash("Please choose a questionnaire file.", "error")
        return redirect(url_for("workflow.dashboard"))

    original_filename = secure_filename(uploaded.filename or "")
    if not original_filename:
        flash("Invalid filename.", "error")
        return redirect(url_for("workflow.dashboard"))

    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_QUESTIONNAIRE_EXTENSIONS:
        flash("Unsupported questionnaire format.", "error")
        return redirect(url_for("workflow.dashboard"))

    stored_name = f"{uuid4().hex}{ext}"
    stored_path = current_app.config["QUESTIONNAIRE_DIR"] / stored_name
    uploaded.save(stored_path)

    try:
        question_texts, parse_meta = parse_questionnaire(stored_path, ext)
    except Exception:
        stored_path.unlink(missing_ok=True)
        flash("Failed to parse questionnaire file.", "error")
        return redirect(url_for("workflow.dashboard"))

    question_texts = [text.strip() for text in question_texts if text and text.strip()]
    if not question_texts:
        stored_path.unlink(missing_ok=True)
        flash("No questions were detected in this file.", "error")
        return redirect(url_for("workflow.dashboard"))

    questionnaire = Questionnaire(
        user_id=current_user.id,
        name=Path(original_filename).stem,
        original_filename=original_filename,
        stored_path=str(stored_path),
        file_ext=ext,
        parser_meta_json=json.dumps(parse_meta),
    )
    db.session.add(questionnaire)
    db.session.flush()

    for index, text in enumerate(question_texts, start=1):
        db.session.add(Question(questionnaire_id=questionnaire.id, position=index, text=text))

    db.session.commit()
    flash(f"Questionnaire uploaded with {len(question_texts)} question(s).", "success")
    return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))


@workflow_bp.route("/questionnaires/<int:questionnaire_id>")
@login_required
def questionnaire_detail(questionnaire_id: int):
    questionnaire = _owned_questionnaire_or_404(questionnaire_id)
    questions = (
        Question.query.filter_by(questionnaire_id=questionnaire.id)
        .order_by(Question.position.asc())
        .all()
    )
    references = (
        ReferenceDocument.query.filter_by(user_id=current_user.id)
        .order_by(ReferenceDocument.created_at.desc())
        .all()
    )
    runs = (
        GenerationRun.query.filter_by(questionnaire_id=questionnaire.id)
        .order_by(GenerationRun.created_at.desc())
        .all()
    )

    run_summaries = []
    for run in runs:
        run_answers = Answer.query.filter_by(run_id=run.id).all()
        total = len(run_answers)
        cited = sum(1 for row in run_answers if row.citations and row.answer_text != "Not found in references.")
        not_found = sum(1 for row in run_answers if row.answer_text == "Not found in references.")
        run_summaries.append({"run": run, "total": total, "cited": cited, "not_found": not_found})

    return render_template(
        "workflow/questionnaire_detail.html",
        questionnaire=questionnaire,
        questions=questions,
        references=references,
        run_summaries=run_summaries,
    )


@workflow_bp.route("/questionnaires/<int:questionnaire_id>/generate", methods=["POST"])
@login_required
def generate(questionnaire_id: int):
    questionnaire = _owned_questionnaire_or_404(questionnaire_id)

    selected_ids = []
    for raw_value in request.form.getlist("reference_ids"):
        if raw_value.isdigit():
            selected_ids.append(int(raw_value))

    reference_query = ReferenceDocument.query.filter_by(user_id=current_user.id)
    if selected_ids:
        reference_query = reference_query.filter(ReferenceDocument.id.in_(selected_ids))
    references = reference_query.order_by(ReferenceDocument.created_at.asc()).all()

    if not references:
        flash("At least one reference document is required to generate answers.", "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

    chunks = chunk_references(
        [{"id": ref.id, "name": ref.original_filename, "text": ref.text_content} for ref in references]
    )
    if not chunks:
        flash("Reference documents do not contain enough text to generate answers.", "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

    try:
        vectorizer, matrix = build_retrieval_index(chunks)
    except ValueError:
        flash("Could not build retrieval index from selected references.", "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

    run = GenerationRun(questionnaire_id=questionnaire.id)
    db.session.add(run)
    db.session.flush()

    questions = (
        Question.query.filter_by(questionnaire_id=questionnaire.id)
        .order_by(Question.position.asc())
        .all()
    )

    for question in questions:
        result = answer_question(question.text, chunks, vectorizer, matrix)
        answer = Answer(
            run_id=run.id,
            question_id=question.id,
            answer_text=result["answer"],
            citations_json=json.dumps(result["citations"]),
            evidence_json=json.dumps(result["evidence"]),
            confidence=result["confidence"],
        )
        db.session.add(answer)

    db.session.commit()
    flash("Answers generated. Please review and edit before exporting.", "success")
    return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))


@workflow_bp.route("/questionnaires/<int:questionnaire_id>/review/<int:run_id>", methods=["GET", "POST"])
@login_required
def review_run(questionnaire_id: int, run_id: int):
    questionnaire = _owned_questionnaire_or_404(questionnaire_id)
    run = GenerationRun.query.filter_by(id=run_id, questionnaire_id=questionnaire.id).first_or_404()
    answers = (
        Answer.query.join(Question, Answer.question_id == Question.id)
        .filter(Answer.run_id == run.id)
        .order_by(Question.position.asc())
        .all()
    )

    if request.method == "POST":
        for answer in answers:
            answer_field = f"answer_{answer.id}"
            citation_field = f"citations_{answer.id}"

            updated_answer = request.form.get(answer_field, "").strip()
            updated_answer = updated_answer or "Not found in references."

            citation_text = request.form.get(citation_field, "")
            citations = [c.strip() for c in re.split(r"[,;\n]+", citation_text) if c.strip()]

            answer.answer_text = updated_answer
            answer.set_citations(citations)
            answer.edited_by_user = True

        db.session.commit()
        flash("Edits saved.", "success")
        return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))

    rows = []
    for answer in answers:
        rows.append(
            {
                "answer_id": answer.id,
                "question": answer.question.text,
                "answer": answer.answer_text,
                "citations": answer.citations,
                "evidence": answer.evidence,
                "confidence": answer.confidence,
                "edited_by_user": answer.edited_by_user,
            }
        )

    coverage = {
        "total_questions": len(rows),
        "answered_with_citations": sum(
            1 for row in rows if row["citations"] and row["answer"] != "Not found in references."
        ),
        "not_found": sum(1 for row in rows if row["answer"] == "Not found in references."),
    }

    return render_template(
        "workflow/review.html",
        questionnaire=questionnaire,
        run=run,
        rows=rows,
        coverage=coverage,
    )


@workflow_bp.route("/questionnaires/<int:questionnaire_id>/export/<int:run_id>")
@login_required
def export_run(questionnaire_id: int, run_id: int):
    questionnaire = _owned_questionnaire_or_404(questionnaire_id)
    run = GenerationRun.query.filter_by(id=run_id, questionnaire_id=questionnaire.id).first_or_404()
    questions = (
        Question.query.filter_by(questionnaire_id=questionnaire.id)
        .order_by(Question.position.asc())
        .all()
    )
    answers = Answer.query.filter_by(run_id=run.id).all()
    answers_by_question_id = {answer.question_id: answer for answer in answers}

    filename, mimetype, data = build_export_payload(questionnaire, questions, answers_by_question_id)
    return send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype,
    )


def _owned_questionnaire_or_404(questionnaire_id: int) -> Questionnaire:
    return Questionnaire.query.filter_by(id=questionnaire_id, user_id=current_user.id).first_or_404()
