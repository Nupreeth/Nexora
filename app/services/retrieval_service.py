import re
from typing import Any, Dict, List, Sequence, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


WORD_RE = re.compile(r"[a-zA-Z]{3,}")
NOT_FOUND = "Not found in references."
QUESTION_STOPWORDS = {
    "and",
    "the",
    "for",
    "all",
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
    "there",
    "that",
    "this",
    "into",
    "under",
    "over",
    "along",
    "also",
    "customer",
    "customers",
    "services",
    "service",
    "support",
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
    top_k: int = 6,
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
    relative_floor = max(min_score * 0.9, best_score * 0.33)
    for index in top_indexes:
        score = float(similarities[index])
        if score < relative_floor:
            continue
        selected.append({**chunks[int(index)], "score": score})
        if len(selected) >= 3:
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
            sentence_words = _normalized_terms_from_text(sentence)
            overlap_count = len(question_words.intersection(sentence_words))
            if overlap_count == 0:
                continue
            min_overlap = 1 if len(question_words) <= 3 else 2
            if overlap_count < min_overlap and len(question_words) >= 5:
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
                    "match_terms": question_words.intersection(sentence_words),
                }
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item["combined_score"], reverse=True)
    chosen = _select_diverse_candidates(candidates, question_words, max_answers=2)

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
    return {term for term in _normalized_terms_from_text(question) if term not in QUESTION_STOPWORDS}


def _normalized_terms_from_text(text: str) -> set[str]:
    return {_normalize_term(token) for token in WORD_RE.findall(text.lower()) if token}


def _normalize_term(token: str) -> str:
    normalized = token.lower()
    for suffix in ("ization", "ations", "ation", "ments", "ment", "ions", "ion", "ing", "ers", "ies", "es", "ed", "s"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
            if suffix == "ies":
                normalized = f"{normalized[:-3]}y"
            else:
                normalized = normalized[: -len(suffix)]
            break
    return normalized


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


def _select_diverse_candidates(
    candidates: Sequence[Dict[str, Any]],
    question_terms: set[str],
    max_answers: int,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    chosen: List[Dict[str, Any]] = [candidates[0]]
    covered_terms = set(candidates[0]["match_terms"])
    top_score = candidates[0]["combined_score"]

    for candidate in candidates[1:]:
        if len(chosen) >= max_answers:
            break
        novel_terms = set(candidate["match_terms"]) - covered_terms
        adds_coverage = len(novel_terms) > 0
        if not adds_coverage:
            continue
        similarity_threshold = 0.93 if len(novel_terms) >= 2 else 0.88
        if any(_too_similar(candidate["text"], existing["text"], threshold=similarity_threshold) for existing in chosen):
            continue
        quality_floor = max(0.18, top_score * 0.32)
        if len(novel_terms) >= 2:
            quality_floor -= 0.03
        if candidate["combined_score"] < quality_floor:
            continue
        chosen.append(candidate)
        covered_terms.update(candidate["match_terms"])
        if question_terms and len(covered_terms) >= max(1, int(len(question_terms) * 0.65)):
            break

    return chosen


def _too_similar(first: str, second: str, threshold: float = 0.8) -> bool:
    first_words = _normalized_terms_from_text(first)
    second_words = _normalized_terms_from_text(second)
    if not first_words or not second_words:
        return False
    overlap = len(first_words.intersection(second_words)) / max(1, len(first_words.union(second_words)))
    return overlap >= threshold


def _not_found_response() -> Dict[str, Any]:
    return {
        "answer": NOT_FOUND,
        "citations": [],
        "evidence": [],
        "confidence": 0.0,
    }
