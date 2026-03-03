import io
import base64
from pathlib import Path
from typing import Dict, Sequence, Tuple

import pandas as pd
from fpdf import FPDF


def build_export_payload(questionnaire, questions: Sequence, answers_by_question_id: Dict[int, object]) -> Tuple[str, str, bytes]:
    ext = questionnaire.file_ext.lower()
    if ext in {".csv", ".xlsx"}:
        return _export_spreadsheet(questionnaire, questions, answers_by_question_id)
    if ext == ".pdf":
        return _export_pdf(questionnaire, questions, answers_by_question_id)
    return _export_text(questionnaire, questions, answers_by_question_id)


def _export_spreadsheet(questionnaire, questions: Sequence, answers_by_question_id: Dict[int, object]) -> Tuple[str, str, bytes]:
    source_bytes = _load_source_bytes(questionnaire)
    if source_bytes:
        source_buffer = io.BytesIO(source_bytes)
        if questionnaire.file_ext.lower() == ".xlsx":
            dataframe = pd.read_excel(source_buffer)
        else:
            dataframe = pd.read_csv(source_buffer)
    else:
        ordered_questions = sorted(questions, key=lambda q: q.position)
        dataframe = pd.DataFrame({"Question": [question.text for question in ordered_questions]})

    row_indexes = questionnaire.parser_meta.get("row_indices", [])
    if len(row_indexes) != len(questions):
        row_indexes = list(range(min(len(dataframe), len(questions))))

    dataframe["Generated Answer"] = ""
    dataframe["Citations"] = ""
    dataframe["Confidence"] = ""

    ordered_questions = sorted(questions, key=lambda q: q.position)
    for row_index, question in zip(row_indexes, ordered_questions):
        answer = answers_by_question_id.get(question.id)
        if not answer:
            continue
        dataframe.at[row_index, "Generated Answer"] = answer.answer_text
        dataframe.at[row_index, "Citations"] = ", ".join(answer.citations)
        dataframe.at[row_index, "Confidence"] = answer.confidence

    stem = _safe_stem(questionnaire.original_filename)
    if questionnaire.file_ext.lower() == ".xlsx":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False)
        return (
            f"{stem}_answered.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            output.getvalue(),
        )

    return f"{stem}_answered.csv", "text/csv", dataframe.to_csv(index=False).encode("utf-8")


def _export_text(questionnaire, questions: Sequence, answers_by_question_id: Dict[int, object]) -> Tuple[str, str, bytes]:
    lines = []
    for question in sorted(questions, key=lambda q: q.position):
        answer = answers_by_question_id.get(question.id)
        answer_text = answer.answer_text if answer else "Not found in references."
        citations = ", ".join(answer.citations) if answer and answer.citations else "None"
        lines.append(question.text)
        lines.append(f"Answer: {answer_text}")
        lines.append(f"Citations: {citations}")
        lines.append("")

    output = "\n".join(lines).encode("utf-8")
    stem = _safe_stem(questionnaire.original_filename)
    return f"{stem}_answered.txt", "text/plain", output


def _export_pdf(questionnaire, questions: Sequence, answers_by_question_id: Dict[int, object]) -> Tuple[str, str, bytes]:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    for question in sorted(questions, key=lambda q: q.position):
        answer = answers_by_question_id.get(question.id)
        answer_text = answer.answer_text if answer else "Not found in references."
        citations = ", ".join(answer.citations) if answer and answer.citations else "None"

        pdf.set_font("Helvetica", style="B", size=11)
        pdf.multi_cell(0, 6.5, _pdf_safe_text(question.text))
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6.5, _pdf_safe_text(f"Answer: {answer_text}"))
        pdf.multi_cell(0, 6.5, _pdf_safe_text(f"Citations: {citations}"))
        pdf.ln(2)

    serialized = pdf.output(dest="S")
    pdf_bytes = serialized.encode("latin-1", errors="replace") if isinstance(serialized, str) else bytes(serialized)
    stem = _safe_stem(questionnaire.original_filename)
    return f"{stem}_answered.pdf", "application/pdf", pdf_bytes


def _safe_stem(filename: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


def _load_source_bytes(questionnaire) -> bytes:
    source_path = Path(questionnaire.stored_path)
    if source_path.exists():
        try:
            return source_path.read_bytes()
        except OSError:
            pass

    encoded = (questionnaire.parser_meta or {}).get("source_b64")
    if not encoded:
        return b""

    try:
        return base64.b64decode(encoded.encode("ascii"), validate=True)
    except Exception:
        return b""


def _pdf_safe_text(text: str) -> str:
    return str(text).encode("latin-1", errors="replace").decode("latin-1")
