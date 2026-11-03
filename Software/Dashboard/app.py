from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import click
from dotenv import load_dotenv
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFError, CSRFProtect


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(mode=0o700, exist_ok=True)

DEV_MODE = os.getenv("ARC_DEV_MODE", "0") == "1"
SECRET_KEY = os.getenv("ARC_SECRET_KEY")

if not SECRET_KEY:
    if DEV_MODE:
        # Development-only convenience. Every restart invalidates sessions.
        SECRET_KEY = secrets.token_urlsafe(64)
        print(
            "WARNING: ARC_DEV_MODE=1 and ARC_SECRET_KEY is unset. "
            "Using an ephemeral development secret."
        )
    else:
        raise RuntimeError(
            "ARC_SECRET_KEY is required. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )

if not DEV_MODE and (
    len(SECRET_KEY) < 48
    or SECRET_KEY.startswith("replace-with-")
    or SECRET_KEY.lower() in {"changeme", "change-me", "secret"}
):
    raise RuntimeError(
        "ARC_SECRET_KEY is too short or still contains an example value. "
        "Use a unique random secret of at least 48 characters."
    )

app = Flask(__name__, instance_path=str(INSTANCE_DIR), instance_relative_config=False)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    MAX_CONTENT_LENGTH=64 * 1024,
    SESSION_COOKIE_NAME="arc_session_dev" if DEV_MODE else "__Host-arc_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_PATH="/",
    SESSION_COOKIE_DOMAIN=None,
    SESSION_COOKIE_SECURE=not DEV_MODE,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_REFRESH_EACH_REQUEST=False,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=not DEV_MODE,
    REMEMBER_COOKIE_SAMESITE="Strict",
    # Flask-WTF passes this directly to itsdangerous as max_age.
    # Use numeric seconds for compatibility across current itsdangerous releases.
    WTF_CSRF_TIME_LIMIT=3600,
)

trusted_hosts = [
    item.strip()
    for item in os.getenv("ARC_TRUSTED_HOSTS", "").split(",")
    if item.strip()
]
if trusted_hosts:
    # Flask 3.1+ host-header validation. Leave unset in development if you
    # intentionally access the server through changing LAN hostnames/IPs.
    app.config["TRUSTED_HOSTS"] = trusted_hosts

csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = None
login_manager.session_protection = "strong"

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["240 per minute"],
    storage_uri=os.getenv("ARC_RATE_LIMIT_STORAGE", "memory://"),
)

password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(48))

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
DATABASE_PATH = Path(os.getenv("ARC_AUTH_DB", str(INSTANCE_DIR / "auth.sqlite3")))

# The dashboard is a presentation/proxy layer, never the robot safety authority.
# It reads the Pi control-plane API server-side so the browser never sees the
# auxiliary/API bearer token.
ROBOT_API_BASE = os.getenv("ARC_ROBOT_API_BASE", "http://127.0.0.1:8766").rstrip("/")
ROBOT_API_TOKEN = os.getenv("ARC_ROBOT_API_TOKEN", "").strip()
ROBOT_API_TIMEOUT_S = float(os.getenv("ARC_ROBOT_API_TIMEOUT_S", "1.5"))
CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
VOICE_SET_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")

# Auxiliary cognition service. The browser never receives this bearer token.
AUX_API_BASE = os.getenv("ARC_AUX_API_BASE", "http://127.0.0.1:8770").rstrip("/")
AUX_API_TOKEN = os.getenv("ARC_AUX_API_TOKEN", "").strip()
AUX_API_TIMEOUT_S = float(os.getenv("ARC_AUX_API_TIMEOUT_S", "8.0"))


def robot_api_request(path: str, *, accept: str = "application/json"):
    url = ROBOT_API_BASE + path
    req = urllib.request.Request(url, headers={"Accept": accept})
    if ROBOT_API_TOKEN:
        req.add_header("Authorization", f"Bearer {ROBOT_API_TOKEN}")
    return urllib.request.urlopen(req, timeout=ROBOT_API_TIMEOUT_S)


def robot_api_json(path: str) -> tuple[dict, int]:
    try:
        with robot_api_request(path) as upstream:
            return json.load(upstream), int(upstream.status)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "robot_api_http_error"}
        payload["available"] = False
        payload["upstream_status"] = int(exc.code)
        return payload, int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "available": False,
            "error": "robot_control_plane_unavailable",
            "detail": str(exc),
        }, 503


def aux_api_request(path: str, *, method: str = "GET", payload: dict | None = None, accept: str = "application/json"):
    url = AUX_API_BASE + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": accept}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if AUX_API_TOKEN:
        headers["Authorization"] = f"Bearer {AUX_API_TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=AUX_API_TIMEOUT_S)


def aux_api_json(path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[dict, int]:
    try:
        with aux_api_request(path, method=method, payload=payload) as upstream:
            return json.load(upstream), int(upstream.status)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {"error": "aux_api_http_error"}
        body["available"] = False
        body["upstream_status"] = int(exc.code)
        return body, int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"available": False, "error": "auxiliary_service_unavailable", "detail": str(exc)}, 503


class User(UserMixin):
    def __init__(self, user_id: int, username: str, active: bool = True):
        self.id = user_id
        self.username = username
        self._active = active

    @property
    def is_active(self) -> bool:
        return self._active


def db_connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                password_changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT
            )
            """
        )

    try:
        os.chmod(DATABASE_PATH, 0o600)
    except OSError:
        # Windows does not implement POSIX mode bits in the same way.
        pass


def get_user_row_by_id(user_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def get_user_row_by_username(username: str) -> sqlite3.Row | None:
    with db_connect() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, active FROM users WHERE username = ?",
            (username,),
        ).fetchone()


def row_to_user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    return User(int(row["id"]), str(row["username"]), bool(row["active"]))


def safe_next_url(target: str | None) -> str | None:
    if not target:
        return None

    host = urlsplit(request.host_url)
    candidate = urlsplit(urljoin(request.host_url, target))

    if candidate.scheme not in {"http", "https"}:
        return None
    if candidate.netloc != host.netloc:
        return None

    return candidate.path + (("?" + candidate.query) if candidate.query else "")


def login_rate_key() -> str:
    username = request.form.get("username", "").strip().casefold()[:64]
    return f"{get_remote_address()}:{username}"


def verify_password_safely(row: sqlite3.Row | None, password: str) -> bool:
    # Always perform an Argon2 verification, even for unknown usernames, to
    # reduce timing differences that can aid account enumeration.
    stored_hash = str(row["password_hash"]) if row is not None else DUMMY_PASSWORD_HASH

    try:
        valid = password_hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False

    return bool(row is not None and valid and row["active"])


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None

    user = row_to_user(get_user_row_by_id(numeric_id))
    if user is None or not user.is_active:
        return None
    return user


@login_manager.unauthorized_handler
def unauthorized():
    next_target = request.full_path if request.query_string else request.path
    return redirect(url_for("login", next=next_target))


@app.after_request
def apply_security_headers(response):
    # Static files may be cached normally; authenticated/document responses
    # should not be retained by shared browser/proxy caches.
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "serial=(), bluetooth=()"
    )
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    # JS contains no inline scripts. The circuit parallax uses a dynamic style
    # transform, so style-src-attr remains enabled while inline <style> blocks
    # and all inline/eval JavaScript remain blocked.
    response.headers["Content-Security-Policy"] = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "style-src-elem 'self'",
            "style-src-attr 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "media-src 'self' blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )

    if not DEV_MODE:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


@app.errorhandler(CSRFError)
def handle_csrf_error(_error):
    return render_template(
        "error.html",
        page_name="error",
        error_code="400",
        error_title="Request rejected",
        error_message="The security token was missing or expired. Reload the page and try again.",
    ), 400


@app.errorhandler(429)
def handle_rate_limit(_error):
    return render_template(
        "error.html",
        page_name="error",
        error_code="429",
        error_title="Too many attempts",
        error_message="Please wait before trying again.",
    ), 429


@app.get("/")
def splash():
    return render_template("splash.html", page_name="splash")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("12 per minute; 60 per hour", key_func=get_remote_address, methods=["POST"])
@limiter.limit("5 per minute; 20 per hour", key_func=login_rate_key, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_target = request.form.get("next") or request.args.get("next")

        structurally_valid = (
            bool(USERNAME_RE.fullmatch(username))
            and 1 <= len(password) <= 256
        )

        row = get_user_row_by_username(username) if structurally_valid else None
        password_ok = verify_password_safely(row, password if len(password) <= 256 else "")

        if structurally_valid and password_ok and row is not None:
            # Upgrade hashes transparently when Argon2 parameters change.
            try:
                if password_hasher.check_needs_rehash(str(row["password_hash"])):
                    new_hash = password_hasher.hash(password)
                    with db_connect() as conn:
                        conn.execute(
                            """
                            UPDATE users
                            SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (new_hash, int(row["id"])),
                        )
            except (InvalidHashError, VerificationError):
                flash("Invalid username or password.", "error")
                return render_template("login.html", page_name="login"), 401

            # Clear any pre-authentication session data to mitigate fixation.
            session.clear()
            session.permanent = True

            user = row_to_user(row)
            login_user(user, remember=False, fresh=True)

            with db_connect() as conn:
                conn.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (int(row["id"]),),
                )

            destination = safe_next_url(next_target) or url_for("dashboard")
            return redirect(destination)

        # Deliberately generic: do not reveal whether an account exists,
        # is disabled, or simply has the wrong password.
        flash("Invalid username or password.", "error")
        return render_template("login.html", page_name="login"), 401

    return render_template("login.html", page_name="login")


@app.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Signed out.", "info")
    return redirect(url_for("login"))


@app.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", page_name="dashboard")


@app.get("/robot")
@login_required
def robot():
    return render_template("robot.html", page_name="robot")


@app.get("/settings")
@login_required
def settings():
    # Settings were consolidated into the information-dense dashboard during R&D.
    # Keep the route as a compatibility redirect for old bookmarks.
    return redirect(url_for("dashboard"))


@app.get("/help")
def help_page():
    return render_template("help.html", page_name="help")


@app.get("/api/robot/state")
@login_required
def api_robot_state():
    payload, status = robot_api_json("/v1/state")
    # A 503 is meaningful to the UI and must not be disguised as healthy state.
    return jsonify(payload), status


@app.get("/api/robot/health")
@login_required
def api_robot_health():
    payload, status = robot_api_json("/v1/health")
    return jsonify(payload), status


@app.get("/api/robot/world")
@login_required
def api_robot_world():
    payload, status = robot_api_json("/v1/world")
    return jsonify(payload), status


@app.get("/api/aux/world")
@login_required
def api_aux_world():
    payload, status = aux_api_json("/v1/world")
    return jsonify(payload), status


@app.get("/api/robot/cameras")
@login_required
def api_robot_cameras():
    payload, status = robot_api_json("/v1/cameras")
    return jsonify(payload), status


@app.get("/api/robot/cameras/<camera_id>/frame")
@login_required
@limiter.limit("240 per minute")
def api_robot_camera_frame(camera_id: str):
    if not CAMERA_ID_RE.fullmatch(camera_id):
        return jsonify({"error": "invalid_camera_id"}), 400
    view = request.args.get("view", "processed")
    if view not in {"raw", "processed"}:
        return jsonify({"error": "invalid_view"}), 400

    path = f"/v1/cameras/{camera_id}/frame?view={view}"
    try:
        with robot_api_request(path, accept="image/jpeg") as upstream:
            body = upstream.read(4 * 1024 * 1024)
            headers = {
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            }
            for key in (
                "X-Automaton-Camera",
                "X-Automaton-View",
                "X-Automaton-Frame-Sequence",
                "X-Automaton-Frame-Age-Ms",
                "X-Automaton-Fallback-From",
            ):
                value = upstream.headers.get(key)
                if value:
                    headers[key] = value
            return Response(body, status=200, mimetype="image/jpeg", headers=headers)
    except urllib.error.HTTPError as exc:
        return jsonify({"error": "frame_unavailable", "upstream_status": int(exc.code)}), int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return jsonify({"error": "robot_control_plane_unavailable", "detail": str(exc)}), 503


@app.get("/api/aux/status")
@login_required
def api_aux_status():
    payload, status = aux_api_json("/v1/status")
    return jsonify(payload), status


@app.get("/api/aux/health")
@login_required
def api_aux_health():
    payload, status = aux_api_json("/v1/health")
    return jsonify(payload), status


@app.get("/api/aux/voices")
@login_required
def api_aux_voices():
    payload, status = aux_api_json("/v1/voices")
    return jsonify(payload), status


@app.get("/api/aux/telemetry")
@login_required
def api_aux_telemetry():
    payload, status = aux_api_json("/v1/telemetry")
    return jsonify(payload), status


@app.post("/api/aux/voice/select")
@login_required
@limiter.limit("30 per minute")
def api_aux_voice_select():
    """Legacy/debug individual-voice selector.

    Normal dashboard operation uses voice sets so multilingual replies keep a
    consistent style/gender preference while still choosing a voice per language.
    """
    data = request.get_json(silent=True) or {}
    voice_id = str(data.get("voice_id", "")).strip()
    if not VOICE_ID_RE.fullmatch(voice_id):
        return jsonify({"error": "invalid_voice_id"}), 400
    payload, status = aux_api_json("/v1/voices/select", method="POST", payload={"voice_id": voice_id})
    return jsonify(payload), status


@app.post("/api/aux/voice-set/select")
@login_required
@limiter.limit("30 per minute")
def api_aux_voice_set_select():
    data = request.get_json(silent=True) or {}
    voice_set_id = str(data.get("voice_set_id", "")).strip()
    if not VOICE_SET_ID_RE.fullmatch(voice_set_id):
        return jsonify({"error": "invalid_voice_set_id"}), 400
    payload, status = aux_api_json(
        "/v1/voice-sets/select",
        method="POST",
        payload={"voice_set_id": voice_set_id},
    )
    return jsonify(payload), status


@app.post("/api/aux/tts/sample")
@login_required
@limiter.limit("20 per minute")
def api_aux_tts_sample():
    data = request.get_json(silent=True) or {}
    text_value = str(data.get("text", "")).strip()
    voice_id = str(data.get("voice_id", "")).strip()
    voice_set_id = str(data.get("voice_set_id", "")).strip()
    if not text_value or len(text_value) > 500:
        return jsonify({"error": "invalid_text"}), 400
    if voice_id and not VOICE_ID_RE.fullmatch(voice_id):
        return jsonify({"error": "invalid_voice_id"}), 400
    if voice_set_id and not VOICE_SET_ID_RE.fullmatch(voice_set_id):
        return jsonify({"error": "invalid_voice_set_id"}), 400
    if voice_id and voice_set_id:
        return jsonify({"error": "ambiguous_voice_selection"}), 400
    body = {"text": text_value}
    if voice_id:
        body["voice_id"] = voice_id
    if voice_set_id:
        body["voice_set_id"] = voice_set_id
    try:
        with aux_api_request("/v1/tts/synthesize", method="POST", payload=body, accept="audio/wav") as upstream:
            audio = upstream.read(8 * 1024 * 1024)
            # Browsers surface an opaque "no supported source" error for an
            # empty/truncated WAV, so fail clearly before handing bad bytes to
            # the <audio> element. Standard PCM WAV starts with RIFF....WAVE.
            if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
                return jsonify({"error": "invalid_tts_audio", "detail": "Auxiliary TTS did not return a valid WAV stream."}), 502
            headers = {
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline; filename=talus-preview.wav",
            }
            selected = upstream.headers.get("X-Automaton-Voice-Id")
            if selected:
                headers["X-Automaton-Voice-Id"] = selected
            selected_set = upstream.headers.get("X-Automaton-Voice-Set-Id")
            if selected_set:
                headers["X-Automaton-Voice-Set-Id"] = selected_set
            return Response(audio, status=200, mimetype="audio/wav", headers=headers)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"error": "tts_unavailable"}
        return jsonify(payload), int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return jsonify({"error": "auxiliary_service_unavailable", "detail": str(exc)}), 503


@app.cli.command("create-user")
@click.argument("username")
@click.password_option(confirmation_prompt=True)
def create_user(username: str, password: str):
    """Create a local dashboard user without exposing a registration route."""
    username = username.strip()

    if not USERNAME_RE.fullmatch(username):
        raise click.ClickException(
            "Username must be 3-64 characters using letters, numbers, ., _, or -."
        )

    if not 15 <= len(password) <= 128:
        raise click.ClickException("Password must be between 15 and 128 characters.")

    if password.casefold() == username.casefold():
        raise click.ClickException("Password must not match the username.")

    password_hash = password_hasher.hash(password)

    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
    except sqlite3.IntegrityError as exc:
        raise click.ClickException("That username already exists.") from exc

    click.echo(f"Created user: {username}")


@app.cli.command("disable-user")
@click.argument("username")
def disable_user(username: str):
    """Disable an account without deleting its security/audit identity."""
    with db_connect() as conn:
        cursor = conn.execute(
            "UPDATE users SET active = 0 WHERE username = ?",
            (username.strip(),),
        )

    if cursor.rowcount == 0:
        raise click.ClickException("User not found.")

    click.echo(f"Disabled user: {username}")


@app.cli.command("set-password")
@click.argument("username")
@click.password_option(confirmation_prompt=True)
def set_password(username: str, password: str):
    """Replace a user's password with a new Argon2id hash."""
    username = username.strip()

    if not 15 <= len(password) <= 128:
        raise click.ClickException("Password must be between 15 and 128 characters.")

    if password.casefold() == username.casefold():
        raise click.ClickException("Password must not match the username.")

    password_hash = password_hasher.hash(password)

    with db_connect() as conn:
        cursor = conn.execute(
            """
            UPDATE users
            SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP
            WHERE username = ?
            """,
            (password_hash, username),
        )

    if cursor.rowcount == 0:
        raise click.ClickException("User not found.")

    click.echo(f"Updated password for: {username}")


init_db()


if __name__ == "__main__":
    # Never use Flask's debug server as the final production deployment path.
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("ARC_PORT", "5000")),
        debug=DEV_MODE,
    )
