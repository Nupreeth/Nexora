import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    SECRET_KEY = os.environ.get("SECRET_KEY", "replace-this-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "20")) * 1024 * 1024

    UPLOAD_FOLDER = BASE_DIR / "uploads"
    QUESTIONNAIRE_DIR = UPLOAD_FOLDER / "questionnaires"
    REFERENCE_DIR = UPLOAD_FOLDER / "references"
    EXPORT_DIR = UPLOAD_FOLDER / "exports"

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
