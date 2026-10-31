"""
Configuration for TaskFlow.

All secrets (database password, Flask secret key) are read from environment
variables. For local development you can put them in a `.env` file, which is
loaded automatically and is ignored by git.
"""
import os
import secrets

from dotenv import load_dotenv
from sqlalchemy.engine import URL

# Load variables from a local .env file if one exists (does nothing otherwise).
load_dotenv()


def _build_database_url():
    """Return the PostgreSQL connection URL built from environment variables.

    Option 1: set DATABASE_URL directly, e.g.
        postgresql://user:password@localhost:5432/taskflow
    Option 2: set the individual DB_* variables (DB_USER, DB_PASSWORD, ...).
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        # Make sure SQLAlchemy uses the psycopg (version 3) driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix):]
                break
        return url

    # URL.create safely escapes special characters in the password.
    return URL.create(
        drivername="postgresql+psycopg",
        username=os.environ.get("DB_USER", "taskflow"),
        password=os.environ.get("DB_PASSWORD") or None,
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "taskflow"),
    ).render_as_string(hide_password=False)


class Config:
    """Base settings shared by every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = _build_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Test each pooled connection before use so the app recovers
        # automatically after PostgreSQL restarts.
        "pool_pre_ping": True,
        # Recycle connections every 30 minutes to avoid stale connections.
        "pool_recycle": 1800,
        # Fail fast (instead of hanging) when the database is unreachable.
        "connect_args": {
            "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "5"))
        },
    }

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Safer session cookie defaults.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set to "true" once the site is served over HTTPS (via Nginx).
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """Local development: debug mode on."""

    DEBUG = True
    # Convenience for local work only: use a random key if none is provided.
    SECRET_KEY = Config.SECRET_KEY or secrets.token_hex(32)


class ProductionConfig(Config):
    """Production (Gunicorn behind Nginx). SECRET_KEY must be set."""


class TestingConfig(Config):
    """Automated tests: in-memory SQLite, so no PostgreSQL server is needed."""

    TESTING = True
    SECRET_KEY = "test-only-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}


_CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    """Pick a config class using the APP_ENV variable (default: production)."""
    env = os.environ.get("APP_ENV", "production").lower()
    return _CONFIGS.get(env, ProductionConfig)
