import json
from datetime import datetime

from flask_login import UserMixin

from .extensions import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class User(UserMixin, TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    questionnaires = db.relationship("Questionnaire", backref="owner", lazy=True)
    reference_documents = db.relationship("ReferenceDocument", backref="owner", lazy=True)


class Questionnaire(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    file_ext = db.Column(db.String(16), nullable=False)
    parser_meta_json = db.Column(db.Text, nullable=False, default="{}")

    questions = db.relationship("Question", backref="questionnaire", lazy=True, cascade="all, delete-orphan")
    runs = db.relationship("GenerationRun", backref="questionnaire", lazy=True, cascade="all, delete-orphan")

    @property
    def parser_meta(self):
        try:
            return json.loads(self.parser_meta_json or "{}")
        except json.JSONDecodeError:
            return {}


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    questionnaire_id = db.Column(db.Integer, db.ForeignKey("questionnaire.id"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)


class ReferenceDocument(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    file_ext = db.Column(db.String(16), nullable=False)
    text_content = db.Column(db.Text, nullable=False)


class GenerationRun(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    questionnaire_id = db.Column(db.Integer, db.ForeignKey("questionnaire.id"), nullable=False, index=True)

    answers = db.relationship("Answer", backref="run", lazy=True, cascade="all, delete-orphan")


class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("generation_run.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False, index=True)
    answer_text = db.Column(db.Text, nullable=False)
    citations_json = db.Column(db.Text, nullable=False, default="[]")
    evidence_json = db.Column(db.Text, nullable=False, default="[]")
    confidence = db.Column(db.Float, nullable=False, default=0.0)
    edited_by_user = db.Column(db.Boolean, nullable=False, default=False)

    question = db.relationship("Question")

    @property
    def citations(self):
        return _decode_json_list(self.citations_json)

    @property
    def evidence(self):
        data = _decode_json_list(self.evidence_json)
        return [item for item in data if isinstance(item, dict)]

    def set_citations(self, citations):
        self.citations_json = json.dumps(citations)

    def set_evidence(self, evidence):
        self.evidence_json = json.dumps(evidence)


def _decode_json_list(value: str):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []
