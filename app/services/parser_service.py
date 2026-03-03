import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from docx import Document
from pypdf import PdfReader


QUESTION_HEADER_RE = re.compile(r"(?m)^\s*(?:q\s*)?\d{1,3}[\).:\-\s]+(.+)$", flags=re.IGNORECASE)


def parse_questionnaire(file_path: Path, extension: str) -> Tuple[List[str], Dict[str, Any]]:
    ext = extension.lower()
    if ext == ".csv":
        return _parse_spreadsheet(file_path, is_excel=False)
    if ext == ".xlsx":
        return _parse_spreadsheet(file_path, is_excel=True)
    if ext == ".pdf":
        text = _extract_pdf_text(file_path)
        return _parse_text_questions(text), {"type": "pdf"}
    if ext == ".txt":
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        return _parse_text_questions(text), {"type": "txt"}
    raise ValueError(f"Unsupported questionnaire extension: {extension}")


def extract_reference_text(file_path: Path, extension: str) -> str:
    ext = extension.lower()
    if ext in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        return _extract_pdf_text(file_path)
    if ext == ".docx":
        doc = Document(file_path)
        return "\n".join(paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip())
    if ext == ".csv":
        df = pd.read_csv(file_path)
        return df.fillna("").astype(str).to_csv(index=False)
    if ext == ".xlsx":
        df = pd.read_excel(file_path)
        return df.fillna("").astype(str).to_csv(index=False)
    raise ValueError(f"Unsupported reference extension: {extension}")


def _parse_spreadsheet(file_path: Path, is_excel: bool) -> Tuple[List[str], Dict[str, Any]]:
    dataframe = pd.read_excel(file_path) if is_excel else pd.read_csv(file_path)
    if dataframe.empty:
        return [], {"type": "xlsx" if is_excel else "csv", "row_indices": []}

    question_column = _select_question_column(dataframe)
    question_rows: List[int] = []
    questions: List[str] = []

    for row_index, raw_value in dataframe[question_column].items():
        text = _normalize_text(raw_value)
        if not text:
            continue
        if _looks_like_question(text):
            question_rows.append(int(row_index))
            questions.append(text)

    if not questions:
        for row_index, raw_value in dataframe[question_column].items():
            text = _normalize_text(raw_value)
            if text:
                question_rows.append(int(row_index))
                questions.append(text)

    meta = {
        "type": "xlsx" if is_excel else "csv",
        "question_column": question_column,
        "row_indices": question_rows,
    }
    return questions, meta


def _parse_text_questions(text: str) -> List[str]:
    text = text.strip()
    if not text:
        return []

    numbered = [match.group(1).strip() for match in QUESTION_HEADER_RE.finditer(text)]
    if numbered:
        return [_normalize_text(item) for item in numbered if _normalize_text(item)]

    lines = [_normalize_text(line) for line in text.splitlines()]
    candidates = [line for line in lines if line and _looks_like_question(line)]
    if candidates:
        return candidates

    sentences = re.split(r"(?<=[?])\s+", text)
    return [_normalize_text(sentence) for sentence in sentences if _normalize_text(sentence)]


def _extract_pdf_text(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = page_text.strip()
        if page_text:
            pages.append(f"[Page {index}]\n{page_text}")
    return "\n\n".join(pages)


def _select_question_column(dataframe: pd.DataFrame) -> str:
    column_map = {str(col).strip().lower(): str(col) for col in dataframe.columns}
    for candidate in ("question", "questions", "prompt", "query"):
        if candidate in column_map:
            return column_map[candidate]

    object_columns = []
    for column in dataframe.columns:
        if pd.api.types.is_object_dtype(dataframe[column]) or pd.api.types.is_string_dtype(dataframe[column]):
            object_columns.append(str(column))

    if object_columns:
        return object_columns[0]
    return str(dataframe.columns[0])


def _looks_like_question(text: str) -> bool:
    lowered = text.lower()
    starts = (
        "do ",
        "does ",
        "is ",
        "are ",
        "what ",
        "which ",
        "when ",
        "where ",
        "who ",
        "how ",
        "describe ",
        "provide ",
        "list ",
        "explain ",
        "can ",
        "please ",
    )
    return "?" in text or lowered.startswith(starts)


def _normalize_text(value: Any) -> str:
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", text)
