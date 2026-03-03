from flask import Flask, render_template

from .config import Config
from .extensions import db, login_manager


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    _ensure_upload_dirs(app)
    _register_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()

    return app


def _register_extensions(app: Flask) -> None:
    db.init_app(app)
    login_manager.init_app(app)

    from .models import User  # noqa: WPS433

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    from .routes.auth import auth_bp  # noqa: WPS433
    from .routes.workflow import workflow_bp  # noqa: WPS433

    app.register_blueprint(auth_bp)
    app.register_blueprint(workflow_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def page_not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("errors/500.html"), 500


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        print("Database initialized.")


def _ensure_upload_dirs(app: Flask) -> None:
    for key in ["UPLOAD_FOLDER", "QUESTIONNAIRE_DIR", "REFERENCE_DIR", "EXPORT_DIR"]:
        app.config[key].mkdir(parents=True, exist_ok=True)
