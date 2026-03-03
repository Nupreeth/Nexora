from app.services.retrieval_service import answer_question, build_retrieval_index, chunk_references


def test_retrieval_returns_grounded_answer():
    references = [
        {
            "id": 1,
            "name": "security_policy.txt",
            "text": "Multi-factor authentication is mandatory for all production admin accounts.",
        }
    ]
    chunks = chunk_references(references)
    vectorizer, matrix = build_retrieval_index(chunks)

    result = answer_question(
        "Do you enforce MFA for production admins?",
        chunks,
        vectorizer,
        matrix,
    )

    assert "Not found in references." not in result["answer"]
    assert result["citations"]
    assert result["confidence"] > 0


def test_retrieval_returns_not_found_for_irrelevant_question():
    references = [{"id": 1, "name": "infra.txt", "text": "Backups are retained for 35 days."}]
    chunks = chunk_references(references)
    vectorizer, matrix = build_retrieval_index(chunks)

    result = answer_question(
        "Do you have an AI ethics board?",
        chunks,
        vectorizer,
        matrix,
    )

    assert result["answer"] == "Not found in references."
    assert result["citations"] == []
