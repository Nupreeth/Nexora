import re
from typing import Any, Dict, List, Sequence, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


WORD_RE = re.compile(r"[a-zA-Z]{3,}")
NOT_FOUND = "Not found in references."


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
    top_k: int = 3,
    min_score: float = 0.12,
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

    selected = []
    for index in top_indexes:
        score = float(similarities[index])
        if score <= 0:
            continue
        selected.append({**chunks[int(index)], "score": score})

    if not selected:
        return _not_found_response()

    extracted_answer = _extract_answer(question, selected)
    if not extracted_answer:
        return _not_found_response()

    citations = list(dict.fromkeys(item["citation"] for item in selected))
    evidence = [
        {
            "citation": item["citation"],
            "snippet": item["text"][:260].replace("\n", " ").strip(),
            "score": round(item["score"], 4),
        }
        for item in selected
    ]
    confidence = round(min(1.0, best_score * 1.65), 2)

    return {
        "answer": extracted_answer,
        "citations": citations,
        "evidence": evidence,
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


def _extract_answer(question: str, selected_chunks: Sequence[Dict[str, Any]]) -> str:
    question_words = set(WORD_RE.findall(question.lower()))
    if not question_words:
        question_words = set(question.lower().split())

    scored_sentences = []
    for chunk in selected_chunks:
        sentences = re.split(r"(?<=[.!?])\s+", chunk["text"])
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 24:
                continue
            sentence_words = set(WORD_RE.findall(sentence.lower()))
            overlap = len(question_words.intersection(sentence_words))
            lexical_score = overlap / max(1, len(question_words))
            score = lexical_score + (chunk["score"] * 0.6)
            if score > 0:
                scored_sentences.append((score, sentence))

    if not scored_sentences:
        fallback = selected_chunks[0]["text"].strip()
        return fallback[:320] if fallback else ""

    scored_sentences.sort(key=lambda item: item[0], reverse=True)
    selected_sentences = []
    for _, sentence in scored_sentences:
        if sentence in selected_sentences:
            continue
        selected_sentences.append(sentence)
        if len(selected_sentences) >= 2:
            break
    return " ".join(selected_sentences).strip()


def _not_found_response() -> Dict[str, Any]:
    return {
        "answer": NOT_FOUND,
        "citations": [],
        "evidence": [],
        "confidence": 0.0,
    }
