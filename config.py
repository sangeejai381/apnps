import os

basedir = os.path.abspath(os.path.dirname(__file__))


def normalize_database_url(url):
    """
    Makes common copy-pasted connection strings (Neon, Render, Heroku-style)
    work with SQLAlchemy + psycopg2 without hand-editing them:
      "postgres://..."   -> "postgresql+psycopg2://..."
      "postgresql://..." -> "postgresql+psycopg2://..."
    Anything else (sqlite://, mysql+pymysql://, already-explicit URLs) is
    left untouched.
    """
    if not url:
        return None
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "apnps-admin-secret-key-change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = (
        normalize_database_url(os.environ.get("DATABASE_URL"))
        or "sqlite:///" + os.path.join(basedir, "school.db")
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # detect stale connections before using them
        "pool_recycle": 300,    # Neon-style serverless Postgres closes idle
                                 # connections from its side; this keeps the
                                 # pool from handing out dead ones
    }
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB — generous for a ~400-row CSV
