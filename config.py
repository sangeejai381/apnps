import os
import secrets

basedir = os.path.abspath(os.path.dirname(__file__))


def _resolve_secret_key():
    """
    Never fall back to a hardcoded string — a guessable SECRET_KEY lets
    anyone forge session cookies and CSRF tokens. If SECRET_KEY isn't set
    in the environment (e.g. no .env / no host-level config), generate a
    strong random one and persist it to a local file so it survives
    restarts (sessions stay valid) without ever being hardcoded in source.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    key_path = os.path.join(basedir, ".secret_key")
    try:
        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                existing = f.read().strip()
            if existing:
                return existing
        generated = secrets.token_hex(32)
        with open(key_path, "w") as f:
            f.write(generated)
        try:
            os.chmod(key_path, 0o600)  # owner-read/write only
        except OSError:
            pass
        return generated
    except OSError:
        # Read-only filesystem or similar — fall back to a key that's at
        # least random for this process (sessions won't survive a restart,
        # but it still can't be guessed from source).
        return secrets.token_hex(32)


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
    SECRET_KEY = _resolve_secret_key()
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

    # -- Session / cookie hardening --
    SESSION_COOKIE_HTTPONLY = True     # JS can't read the session cookie (mitigates XSS cookie theft)
    SESSION_COOKIE_SAMESITE = "Lax"    # blocks the cookie being sent on cross-site requests (CSRF defense-in-depth)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # auto-expire an idle admin session after 8 hours
    # Only require HTTPS-only cookies once actually deployed behind HTTPS —
    # forcing it in local http:// development would silently break login.
    SESSION_COOKIE_SECURE = os.environ.get("FORCE_HTTPS_COOKIES", "0") == "1"
