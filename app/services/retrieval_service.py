import re
from typing import Any, Dict, List, Sequence, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


WORD_RE = re.compile(r"[a-zA-Z]{3,}")
NOT_FOUND = "Not found in references."
QUESTION_STOPWORDS = {
    "what",
    "which",
    "when",
    "where",
    "who",
    "how",
    "does",
    "do",
    "is",
    "are",
    "can",
    "please",
    "describe",
    "provide",
    "your",
    "their",
    "about",
    "with",
    "from",
    "after",
    "before",
    "between",
    "have",
    "has",
}


def chunk_references(reference_documents: Sequence[Dict[str, Any]], max_chars: int = 700) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for doc in reference_documents:
        text = (doc.get("text") or "").strip()
        if not text:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        current = ""
        chunk_number = 1
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 1 <= max_chars:
                current = f"{current}\n{paragraph}".strip()
                continue
            if current:
                chunks.append(_format_chunk(doc, current, chunk_number))
                chunk_number += 1
            current = paragraph
        if current:
            chunks.append(_format_chunk(doc, current, chunk_number))
    return chunks


def build_retrieval_index(chunks: Sequence[Dict[str, Any]]) -> Tuple[TfidfVectorizer, Any]:
    corpus = [chunk["text"] for chunk in chunks]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(corpus)
    return vectorizer, matrix


def answer_question(
    question: str,
    chunks: Sequence[Dict[str, Any]],
    vectorizer: TfidfVectorizer,
    matrix: Any,
    top_k: int = 5,
    min_score: float = 0.14,
) -> Dict[str, Any]:
    if not chunks:
        return _not_found_response()

    query_vector = vectorizer.transform([question])
    similarities = cosine_similarity(query_vector, matrix).flatten()
    if similarities.size == 0:
        return _not_found_response()

    ranked = similarities.argsort()[::-1]
    top_indexes = ranked[:top_k]
    best_score = float(similarities[top_indexes[0]]) if len(top_indexes) else 0.0
    if best_score < min_score:
        return _not_found_response()

    selected: List[Dict[str, Any]] = []
    relative_floor = max(min_score, best_score * 0.45)
    for index in top_indexes:
        score = float(similarities[index])
        if score < relative_floor:
            continue
        selected.append({**chunks[int(index)], "score": score})
        if len(selected) >= 2:
            break

    if not selected:
        return _not_found_response()

    extracted = _extract_answer(question, selected)
    if not extracted:
        return _not_found_response()

    if extracted["support_score"] < 0.28:
        return _not_found_response()

    confidence = round(min(0.99, (best_score * 1.25) + (extracted["support_score"] * 0.45)), 2)

    return {
        "answer": extracted["answer"],
        "citations": extracted["citations"],
        "evidence": extracted["evidence"],
        "confidence": confidence,
    }


def _format_chunk(document: Dict[str, Any], text: str, number: int) -> Dict[str, Any]:
    doc_name = document.get("name", "reference")
    return {
        "document_id": document.get("id"),
        "document_name": doc_name,
        "chunk_number": number,
        "citation": f"{doc_name}#chunk-{number}",
        "text": text.strip(),
    }


def _extract_answer(question: str, selected_chunks: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    question_words = _question_terms(question)
    if not question_words:
        question_words = set(WORD_RE.findall(question.lower()))

    candidates: List[Dict[str, Any]] = []
    for chunk in selected_chunks:
        for unit in _split_text_units(chunk["text"]):
            sentence = _clean_unit(unit)
            if len(sentence) < 18:
                continue
            sentence_words = set(WORD_RE.findall(sentence.lower()))
            overlap_count = len(question_words.intersection(sentence_words))
            if overlap_count == 0:
                continue
            lexical_score = overlap_count / max(1, len(question_words))
            combined_score = lexical_score + (chunk["score"] * 0.65)
            if combined_score < 0.22:
                continue
            candidates.append(
                {
                    "text": sentence,
                    "citation": chunk["citation"],
                    "combined_score": combined_score,
                    "chunk_score": chunk["score"],
                }
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["combined_score"], reverse=True)
    chosen: List[Dict[str, Any]] = []
    for item in candidates:
        if any(_too_similar(item["text"], existing["text"]) for existing in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= 2:
            break

    if not chosen:
        return None

    answer = " ".join(item["text"] for item in chosen).strip()
    citations = list(dict.fromkeys(item["citation"] for item in chosen))
    evidence = [
        {
            "citation": item["citation"],
            "snippet": item["text"][:230],
            "score": round(item["chunk_score"], 4),
        }
        for item in chosen
    ]
    return {
        "answer": answer,
        "citations": citations,
        "evidence": evidence,
        "support_score": float(chosen[0]["combined_score"]),
    }


def _question_terms(question: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(question.lower())
        if token.lower() not in QUESTION_STOPWORDS
    }


def _split_text_units(text: str) -> List[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("-"):
            lines.append(line.lstrip("- ").strip())
            continue
        if len(line) > 35 and line.endswith("."):
            lines.append(line)

    if len(lines) < 2:
        plain = text.replace("\n", " ")
        lines.extend([segment.strip() for segment in re.split(r"(?<=[.!?])\s+", plain) if segment.strip()])

    deduped = []
    seen = set()
    for item in lines:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _clean_unit(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"[A-Za-z0-9\s/&\-]{1,45}", cleaned) and cleaned == cleaned.title():
        return ""
    return cleaned


def _too_similar(first: str, second: str) -> bool:
    first_words = set(WORD_RE.findall(first.lower()))
    second_words = set(WORD_RE.findall(second.lower()))
    if not first_words or not second_words:
        return False
    overlap = len(first_words.intersection(second_words)) / max(1, len(first_words.union(second_words)))
    return overlap >= 0.8


def _not_found_response() -> Dict[str, Any]:
    return {
        "answer": NOT_FOUND,
        "citations": [],
        "evidence": [],
        "confidence": 0.0,
    }
