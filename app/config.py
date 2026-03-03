import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _build_database_uri(default_path: Path) -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return f"sqlite:///{default_path}"

    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", 1)
    if raw.startswith("postgresql://") and "+psycopg" not in raw:
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    SECRET_KEY = os.environ.get("SECRET_KEY", "replace-this-in-production")
    SQLALCHEMY_DATABASE_URI = _build_database_uri(BASE_DIR / "app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "20")) * 1024 * 1024

    UPLOAD_FOLDER = BASE_DIR / "uploads"
    QUESTIONNAIRE_DIR = UPLOAD_FOLDER / "questionnaires"
    REFERENCE_DIR = UPLOAD_FOLDER / "references"
    EXPORT_DIR = UPLOAD_FOLDER / "exports"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
