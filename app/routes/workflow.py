import io
import json
import re
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Answer,
    ChatMessage,
    ChatSession,
    GenerationRun,
    GenerationRunReference,
    Question,
    Questionnaire,
    ReferenceDocument,
)
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
    recent_runs = (
        GenerationRun.query.join(Questionnaire, GenerationRun.questionnaire_id == Questionnaire.id)
        .filter(Questionnaire.user_id == current_user.id)
        .order_by(GenerationRun.created_at.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "workflow/dashboard.html",
        questionnaires=questionnaires,
        references=references,
        recent_runs=recent_runs,
    )


@workflow_bp.route("/assistant", methods=["GET"])
@login_required
def assistant():
    sessions = (
        ChatSession.query.filter_by(user_id=current_user.id)
        .order_by(ChatSession.created_at.desc())
        .all()
    )
    if not sessions:
        new_session = ChatSession(user_id=current_user.id, title="New chat")
        db.session.add(new_session)
        db.session.commit()
        return redirect(url_for("workflow.assistant", session_id=new_session.id))

    requested_session_id = request.args.get("session_id", type=int)
    active_session = None
    if requested_session_id is not None:
        active_session = ChatSession.query.filter_by(
            id=requested_session_id,
            user_id=current_user.id,
        ).first()
    if active_session is None:
        active_session = sessions[0]

    messages = (
        ChatMessage.query.filter_by(session_id=active_session.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    references_count = ReferenceDocument.query.filter_by(user_id=current_user.id).count()

    return render_template(
        "workflow/assistant.html",
        sessions=sessions,
        active_session=active_session,
        messages=messages,
        references_count=references_count,
    )


@workflow_bp.route("/assistant/sessions", methods=["POST"])
@login_required
def create_chat_session():
    session = ChatSession(user_id=current_user.id, title="New chat")
    db.session.add(session)
    db.session.commit()
    return redirect(url_for("workflow.assistant", session_id=session.id))


@workflow_bp.route("/assistant/sessions/<int:session_id>/messages", methods=["POST"])
@login_required
def assistant_send_message(session_id: int):
    session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first_or_404()
    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        flash("Please enter a message.", "error")
        return redirect(url_for("workflow.assistant", session_id=session.id))

    references = (
        ReferenceDocument.query.filter_by(user_id=current_user.id)
        .order_by(ReferenceDocument.created_at.asc())
        .all()
    )
    if not references:
        flash("Upload reference documents before using assistant chat.", "error")
        return redirect(url_for("workflow.assistant", session_id=session.id))

    user_message = ChatMessage(
        session_id=session.id,
        role="user",
        message_text=prompt,
        citations_json="[]",
        evidence_json="[]",
        confidence=1.0,
    )
    db.session.add(user_message)

    result = _answer_from_references(prompt, references)
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        message_text=result["answer"],
        citations_json=json.dumps(result["citations"]),
        evidence_json=json.dumps(result["evidence"]),
        confidence=result["confidence"],
    )
    db.session.add(assistant_message)

    if session.title == "New chat":
        session.title = _derive_chat_title(prompt)

    db.session.commit()
    return redirect(url_for("workflow.assistant", session_id=session.id))


@workflow_bp.route("/references/upload", methods=["POST"])
@login_required
def upload_references():
    uploaded_files = request.files.getlist("reference_files")
    if not uploaded_files:
        flash("Please choose one or more reference files.", "error")
        return redirect(url_for("workflow.dashboard"))

    created_docs = _store_reference_documents(uploaded_files, flash_errors=True)
    if not created_docs:
        db.session.rollback()
        return redirect(url_for("workflow.dashboard"))

    db.session.commit()
    flash(f"Uploaded {len(created_docs)} reference document(s).", "success")
    return redirect(url_for("workflow.dashboard"))


@workflow_bp.route("/questionnaires/upload", methods=["POST"])
@login_required
def upload_questionnaire():
    uploaded = request.files.get("questionnaire_file")
    questionnaire, question_count = _store_questionnaire(uploaded)
    if not questionnaire:
        return redirect(url_for("workflow.dashboard"))

    db.session.commit()
    flash(f"Questionnaire uploaded with {question_count} question(s).", "success")
    return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))


@workflow_bp.route("/quick-generate", methods=["POST"])
@login_required
def quick_generate():
    questionnaire_upload = request.files.get("questionnaire_file")
    reference_uploads = request.files.getlist("reference_files")
    use_existing_refs = request.form.get("use_existing_refs") == "on"

    questionnaire, question_count = _store_questionnaire(questionnaire_upload)
    if not questionnaire:
        db.session.rollback()
        return redirect(url_for("workflow.dashboard"))

    new_docs = _store_reference_documents(reference_uploads, flash_errors=True)
    selected_references = []

    if use_existing_refs:
        selected_references = (
            ReferenceDocument.query.filter_by(user_id=current_user.id)
            .order_by(ReferenceDocument.created_at.asc())
            .all()
        )
    else:
        selected_references = new_docs

    if not selected_references:
        db.session.commit()
        flash("Questionnaire uploaded, but no usable references were selected.", "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

    try:
        run = _run_generation(questionnaire, selected_references)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

    db.session.commit()
    if new_docs:
        flash(
            f"Smooth run complete: {question_count} questions parsed, {len(new_docs)} new references added.",
            "success",
        )
    else:
        flash(f"Smooth run complete: {question_count} questions parsed.", "success")
    return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))


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

    try:
        run = _run_generation(questionnaire, references)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("workflow.questionnaire_detail", questionnaire_id=questionnaire.id))

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
    chat_session = _find_run_chat_session(questionnaire, run)
    chat_messages = []
    if chat_session:
        chat_messages = (
            ChatMessage.query.filter_by(session_id=chat_session.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
    run_references = _references_for_run(run, current_user.id)

    return render_template(
        "workflow/review.html",
        questionnaire=questionnaire,
        run=run,
        rows=rows,
        coverage=coverage,
        chat_messages=chat_messages,
        run_references=run_references,
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


@workflow_bp.route("/questionnaires/<int:questionnaire_id>/review/<int:run_id>/chat", methods=["POST"])
@login_required
def review_chat(questionnaire_id: int, run_id: int):
    questionnaire = _owned_questionnaire_or_404(questionnaire_id)
    run = GenerationRun.query.filter_by(id=run_id, questionnaire_id=questionnaire.id).first_or_404()
    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        flash("Please enter a follow-up question.", "error")
        return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))

    include_other_data = request.form.get("include_other_data") == "on"
    if include_other_data:
        references = (
            ReferenceDocument.query.filter_by(user_id=current_user.id)
            .order_by(ReferenceDocument.created_at.asc())
            .all()
        )
    else:
        references = _references_for_run(run, current_user.id)

    if not references:
        references = (
            ReferenceDocument.query.filter_by(user_id=current_user.id)
            .order_by(ReferenceDocument.created_at.asc())
            .all()
        )
    if not references:
        flash("Upload reference documents before using chat.", "error")
        return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))

    chat_session = _get_or_create_run_chat_session(questionnaire, run)
    db.session.add(
        ChatMessage(
            session_id=chat_session.id,
            role="user",
            message_text=prompt,
            citations_json="[]",
            evidence_json="[]",
            confidence=1.0,
        )
    )
    result = _answer_from_references(prompt, references)
    db.session.add(
        ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            message_text=result["answer"],
            citations_json=json.dumps(result["citations"]),
            evidence_json=json.dumps(result["evidence"]),
            confidence=result["confidence"],
        )
    )
    db.session.commit()
    return redirect(url_for("workflow.review_run", questionnaire_id=questionnaire.id, run_id=run.id))


def _owned_questionnaire_or_404(questionnaire_id: int) -> Questionnaire:
    return Questionnaire.query.filter_by(id=questionnaire_id, user_id=current_user.id).first_or_404()


def _store_questionnaire(uploaded_file) -> tuple[Questionnaire | None, int]:
    if not uploaded_file:
        flash("Please choose a questionnaire file.", "error")
        return None, 0

    original_filename = secure_filename(uploaded_file.filename or "")
    if not original_filename:
        flash("Invalid questionnaire filename.", "error")
        return None, 0

    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_QUESTIONNAIRE_EXTENSIONS:
        flash("Unsupported questionnaire format.", "error")
        return None, 0

    stored_name = f"{uuid4().hex}{extension}"
    stored_path = current_app.config["QUESTIONNAIRE_DIR"] / stored_name
    uploaded_file.save(stored_path)

    try:
        question_texts, parse_meta = parse_questionnaire(stored_path, extension)
    except Exception:
        stored_path.unlink(missing_ok=True)
        flash("Failed to parse questionnaire file.", "error")
        return None, 0

    question_texts = [text.strip() for text in question_texts if text and text.strip()]
    if not question_texts:
        stored_path.unlink(missing_ok=True)
        flash("No questions were detected in this file.", "error")
        return None, 0

    questionnaire = Questionnaire(
        user_id=current_user.id,
        name=Path(original_filename).stem,
        original_filename=original_filename,
        stored_path=str(stored_path),
        file_ext=extension,
        parser_meta_json=json.dumps(parse_meta),
    )
    db.session.add(questionnaire)
    db.session.flush()

    for index, text in enumerate(question_texts, start=1):
        db.session.add(Question(questionnaire_id=questionnaire.id, position=index, text=text))

    return questionnaire, len(question_texts)


def _store_reference_documents(uploaded_files, flash_errors: bool = True) -> list[ReferenceDocument]:
    created_docs: list[ReferenceDocument] = []
    for uploaded in uploaded_files:
        original_filename = secure_filename(uploaded.filename or "")
        if not original_filename:
            continue

        extension = Path(original_filename).suffix.lower()
        if extension not in ALLOWED_REFERENCE_EXTENSIONS:
            if flash_errors:
                flash(f"Skipped {original_filename}: unsupported file format.", "error")
            continue

        stored_name = f"{uuid4().hex}{extension}"
        stored_path = current_app.config["REFERENCE_DIR"] / stored_name
        uploaded.save(stored_path)

        try:
            text_content = extract_reference_text(stored_path, extension)
        except Exception:
            stored_path.unlink(missing_ok=True)
            if flash_errors:
                flash(f"Skipped {original_filename}: failed to parse.", "error")
            continue

        if not text_content.strip():
            stored_path.unlink(missing_ok=True)
            if flash_errors:
                flash(f"Skipped {original_filename}: no readable content.", "error")
            continue

        document = ReferenceDocument(
            user_id=current_user.id,
            original_filename=original_filename,
            stored_path=str(stored_path),
            file_ext=extension,
            text_content=text_content,
        )
        db.session.add(document)
        created_docs.append(document)
    return created_docs


def _run_generation(questionnaire: Questionnaire, references: list[ReferenceDocument]) -> GenerationRun:
    chunks = chunk_references(
        [{"id": ref.id, "name": ref.original_filename, "text": ref.text_content} for ref in references]
    )
    if not chunks:
        raise ValueError("Reference documents do not contain enough text to generate answers.")

    try:
        vectorizer, matrix = build_retrieval_index(chunks)
    except ValueError as exc:
        raise ValueError("Could not build retrieval index from selected references.") from exc

    run = GenerationRun(questionnaire_id=questionnaire.id)
    db.session.add(run)
    db.session.flush()
    for reference in references:
        db.session.add(GenerationRunReference(run_id=run.id, reference_document_id=reference.id))

    questions = (
        Question.query.filter_by(questionnaire_id=questionnaire.id)
        .order_by(Question.position.asc())
        .all()
    )
    for question in questions:
        result = answer_question(question.text, chunks, vectorizer, matrix)
        db.session.add(
            Answer(
                run_id=run.id,
                question_id=question.id,
                answer_text=result["answer"],
                citations_json=json.dumps(result["citations"]),
                evidence_json=json.dumps(result["evidence"]),
                confidence=result["confidence"],
            )
        )

    return run


def _answer_from_references(prompt: str, references: list[ReferenceDocument]) -> dict:
    chunks = chunk_references(
        [{"id": ref.id, "name": ref.original_filename, "text": ref.text_content} for ref in references]
    )
    if not chunks:
        return {
            "answer": "Not found in references.",
            "citations": [],
            "evidence": [],
            "confidence": 0.0,
        }
    try:
        vectorizer, matrix = build_retrieval_index(chunks)
    except ValueError:
        return {
            "answer": "Not found in references.",
            "citations": [],
            "evidence": [],
            "confidence": 0.0,
        }
    return answer_question(prompt, chunks, vectorizer, matrix)


def _derive_chat_title(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)
    if not words:
        return "New chat"
    candidate = " ".join(words[:7]).strip()
    if len(candidate) > 50:
        return f"{candidate[:47].rstrip()}..."
    return candidate


def _get_or_create_run_chat_session(questionnaire: Questionnaire, run: GenerationRun) -> ChatSession:
    title = f"Run {run.id} | {questionnaire.name}"
    session = ChatSession.query.filter_by(user_id=current_user.id, title=title).first()
    if session:
        return session
    session = ChatSession(user_id=current_user.id, title=title)
    db.session.add(session)
    db.session.flush()
    return session


def _find_run_chat_session(questionnaire: Questionnaire, run: GenerationRun) -> ChatSession | None:
    title = f"Run {run.id} | {questionnaire.name}"
    return ChatSession.query.filter_by(user_id=current_user.id, title=title).first()


def _references_for_run(run: GenerationRun, user_id: int) -> list[ReferenceDocument]:
    links = (
        GenerationRunReference.query.filter_by(run_id=run.id)
        .order_by(GenerationRunReference.id.asc())
        .all()
    )
    if not links:
        return []

    reference_ids = [link.reference_document_id for link in links]
    return (
        ReferenceDocument.query.filter(
            ReferenceDocument.user_id == user_id,
            ReferenceDocument.id.in_(reference_ids),
        )
        .order_by(ReferenceDocument.created_at.asc())
        .all()
    )
