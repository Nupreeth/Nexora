from pathlib import Path

from app.services.parser_service import parse_questionnaire


def test_parse_questionnaire_csv_detects_questions(tmp_path: Path):
    source = tmp_path / "questionnaire.csv"
    source.write_text(
        "Question,Notes\n"
        "Do you enforce MFA?,Yes/No\n"
        "How long are logs retained?,In days\n"
        ",blank row\n",
        encoding="utf-8",
    )

    questions, meta = parse_questionnaire(source, ".csv")

    assert len(questions) == 2
    assert questions[0] == "Do you enforce MFA?"
    assert meta["type"] == "csv"
    assert meta["question_column"] == "Question"
    assert meta["row_indices"] == [0, 1]


def test_parse_questionnaire_txt_extracts_questions(tmp_path: Path):
    source = tmp_path / "questionnaire.txt"
    source.write_text(
        "1) Do you have SSO?\n"
        "2) What is your backup schedule?\n",
        encoding="utf-8",
    )

    questions, meta = parse_questionnaire(source, ".txt")

    assert len(questions) == 2
    assert questions[0] == "Do you have SSO?"
    assert meta["type"] == "txt"
