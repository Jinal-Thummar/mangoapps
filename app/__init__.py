"""
TaskFlow application package.

`create_app()` is an "application factory": it builds and configures a new
Flask app. This makes the app easy to test and easy to run under Gunicorn.
"""
import logging
import sys

from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config

# The database object is created here and connected to the app in create_app().
db = SQLAlchemy()


def create_app(config_class=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    config_class = config_class or get_config()
    app.config.from_object(config_class)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )

    configure_logging(app)

    # Nginx sits in front of Gunicorn and forwards the real client IP, scheme
    # (http/https) and host in X-Forwarded-* headers. ProxyFix tells Flask to
    # trust exactly one proxy hop, so url_for() and logs use the correct values.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)

    from app.routes import bp
    app.register_blueprint(bp)

    register_error_handlers(app)
    register_commands(app)

    # Create the tasks table if it does not exist yet. If PostgreSQL is down we
    # log the problem but still start, so /health can report 503.
    with app.app_context():
        from app import models  # noqa: F401  (registers the Task model)
        try:
            db.create_all()
        except SQLAlchemyError as exc:
            # Several Gunicorn workers start at the same time and may all try to
            # create the table; only one wins. If the table exists now, that is fine.
            if _tasks_table_exists():
                app.logger.info("Database tables already created by another worker.")
            else:
                app.logger.error("Could not initialise database tables: %s", exc)

    app.logger.info("TaskFlow started with %s", config_class.__name__)
    return app


def _tasks_table_exists():
    """Return True if the tasks table exists (False if the DB is unreachable)."""
    try:
        return inspect(db.engine).has_table("tasks")
    except SQLAlchemyError:
        return False


def configure_logging(app):
    """Send logs to stdout so Gunicorn / systemd / journald can collect them."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(app.config["LOG_LEVEL"])
    app.logger.propagate = False


def register_error_handlers(app):
    """Show friendly error pages instead of raw stack traces."""

    @app.errorhandler(404)
    def not_found(error):
        return render_template(
            "error.html", code=404, message="The page or task you requested was not found."
        ), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return render_template(
            "error.html", code=405, message="That action is not allowed."
        ), 405

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception("Database error: %s", error)
        return render_template(
            "error.html", code=503,
            message="The database is temporarily unavailable. Please try again shortly.",
        ), 503

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.exception("Unhandled server error: %s", error)
        return render_template(
            "error.html", code=500, message="Something went wrong on our side."
        ), 500


def register_commands(app):
    """Add custom `flask` CLI commands."""

    @app.cli.command("init-db")
    def init_db():
        """Create database tables (safe to run more than once)."""
        db.create_all()
        print("Database tables created.")
