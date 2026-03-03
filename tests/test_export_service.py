import json
from pathlib import Path
from types import SimpleNamespace

from app.services.export_service import build_export_payload


def test_export_csv_preserves_rows_and_injects_answers(tmp_path: Path):
    source_csv = tmp_path / "q.csv"
    source_csv.write_text(
        "Question\n"
        "Do you enforce MFA?\n"
        "How long are logs retained?\n",
        encoding="utf-8",
    )

    questionnaire = SimpleNamespace(
        file_ext=".csv",
        original_filename="q.csv",
        stored_path=str(source_csv),
        parser_meta={"row_indices": [0, 1]},
    )
    questions = [
        SimpleNamespace(id=101, position=1, text="Do you enforce MFA?"),
        SimpleNamespace(id=102, position=2, text="How long are logs retained?"),
    ]
    answers = {
        101: SimpleNamespace(answer_text="Yes, MFA is mandatory.", citations=["security.txt#chunk-1"], confidence=0.92),
        102: SimpleNamespace(answer_text="Logs retained for 365 days.", citations=["security.txt#chunk-2"], confidence=0.88),
    }

    filename, mimetype, payload = build_export_payload(questionnaire, questions, answers)

    assert filename.endswith("_answered.csv")
    assert mimetype == "text/csv"
    text = payload.decode("utf-8")
    assert "Generated Answer" in text
    assert "Yes, MFA is mandatory." in text
