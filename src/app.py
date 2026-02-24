import base64
import hashlib
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken

from config import DEFAULT_TARASSUL_BASE_URL

_project_root = Path(__file__).resolve().parent.parent
_config_path = _project_root / "data" / "netmon.conf"
_example_path = _project_root / "data" / "netmon.conf.example"
if not _config_path.exists():
    _config_path.parent.mkdir(parents=True, exist_ok=True)
    if _example_path.exists():
        shutil.copy(_example_path, _config_path)
    else:
        _config_path.touch()
load_dotenv(_config_path)


def _fernet():
    secret = os.environ.get("ENCRYPTION_KEY") or os.environ.get("JWT_SECRET") or "change-me-in-production"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _decrypt_password(enc_value: str) -> str:
    if not (enc_value or "").strip():
        return ""
    try:
        return _fernet().decrypt(enc_value.strip().encode()).decode()
    except (InvalidToken, Exception):
        return ""


def _encrypt_password(plain: str) -> str:
    if not (plain or "").strip():
        return ""
    return _fernet().encrypt(plain.strip().encode()).decode()


def _resolve_encrypted(key_enc: str, key_plain: str) -> None:
    enc = (os.environ.get(key_enc) or "").strip()
    if enc:
        dec = _decrypt_password(enc)
        if dec:
            os.environ[key_plain] = dec

_resolve_encrypted("ADMIN_PASSWORD_ENC", "ADMIN_PASSWORD")
_resolve_encrypted("TARASSUL_PASSWORD_ENC", "TARASSUL_PASSWORD")
_resolve_encrypted("NTFY_TOKEN_ENC", "NTFY_TOKEN")


def _ensure_conf_default(key: str, default_value: str) -> None:
    if (os.environ.get(key) or "").strip():
        return
    os.environ[key] = default_value
    path = _config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith(f"{key}=")]
    lines.append(f"{key}={default_value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


_ensure_conf_default("TARASSUL_BASE_URL", DEFAULT_TARASSUL_BASE_URL)
_ensure_conf_default("ENABLE_SCHEDULE", "true")

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    set_access_cookies,
    unset_jwt_cookies,
    jwt_required,
    verify_jwt_in_request,
)
from flask_jwt_extended.exceptions import NoAuthorizationError
from datetime import datetime, timedelta

import db
from fetcher import run_fetch, send_ntfy_test
from scheduler import start_scheduler, reschedule as scheduler_reschedule

db.init_db()

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "change-me-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

jwt = JWTManager(app)


def _api_request() -> bool:
    return request.path.startswith("/api/")


@app.errorhandler(500)
def handle_500(e):
    if _api_request():
        return jsonify({"ok": False, "error": str(e) if str(e) else "Internal server error"}), 500
    raise


@app.errorhandler(404)
def handle_404(e):
    if _api_request():
        return jsonify({"ok": False, "error": "Not found"}), 404
    raise


@jwt.unauthorized_loader
def jwt_unauthorized_callback(_reason):
    if _api_request():
        return jsonify({"ok": False, "error": "Login required"}), 401
    from flask import redirect as flask_redirect
    return flask_redirect(url_for("login"))


@jwt.invalid_token_loader
def jwt_invalid_token_callback(_reason):
    if _api_request():
        return jsonify({"ok": False, "error": "Invalid or expired session"}), 401
    from flask import redirect as flask_redirect
    return flask_redirect(url_for("login"))


@jwt.expired_token_loader
def jwt_expired_callback(_header, _payload):
    if _api_request():
        return jsonify({"ok": False, "error": "Session expired"}), 401
    from flask import redirect as flask_redirect
    return flask_redirect(url_for("login"))


def _admin_username():
    return (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"


def _admin_password():
    return (os.environ.get("ADMIN_PASSWORD") or "").strip()


def _has_admin_password():
    return bool(_admin_password())


def _update_netmon_conf_admin(username: str, password: str) -> None:
    path = _config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    username = (username or "").strip().replace("\n", " ").replace("\r", " ")[:200]
    password = (password or "").strip().replace("\n", " ").replace("\r", " ")[:500]
    enc = _encrypt_password(password)
    new_lines = [f"ADMIN_USERNAME={username}", f"ADMIN_PASSWORD_ENC={enc}"]

    def drop_admin_lines(line: str) -> bool:
        s = line.strip()
        return not (
            s.startswith("ADMIN_USERNAME=")
            or s.startswith("ADMIN_PASSWORD=")
            or s.startswith("ADMIN_PASSWORD_ENC=")
        )

    if path.exists():
        content = path.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            lines = [line for line in content.splitlines() if drop_admin_lines(line)]
            path.write_text("\n".join(lines) + "\n" + "\n".join(new_lines) + "\n", encoding="utf-8")
            return
    if _example_path.exists():
        lines = [
            line
            for line in _example_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if drop_admin_lines(line)
        ]
        path.write_text("\n".join(lines) + "\n" + "\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


_SETTINGS_KEYS_PLAIN = (
    "TARASSUL_BASE_URL", "TARASSUL_USERNAME",
    "TARASSUL_FID", "TARASSUL_LANG",
    "ENABLE_SCHEDULE", "FETCH_HOUR_2", "NTFY_URL", "THEME",
)


def _drop_line_if(line: str, prefixes: tuple) -> bool:
    s = line.strip()
    return any(s.startswith(p) for p in prefixes)


def _update_netmon_conf_settings(updates: dict) -> None:
    path = _config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = content.splitlines()
    sanitize = lambda v: (v or "").strip().replace("\n", " ").replace("\r", " ")[:500]
    for key in _SETTINGS_KEYS_PLAIN:
        if key not in updates:
            continue
        value = sanitize(updates[key])
        os.environ[key] = value
        prefix = f"{key}="
        new_line = f"{key}={value}"
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(prefix):
                lines[i] = new_line
                found = True
                break
        if not found:
            lines.append(new_line)

    raw_pwd = updates.get("TARASSUL_PASSWORD")
    if raw_pwd is not None and raw_pwd != "" and raw_pwd != "********":
        plain = sanitize(raw_pwd)
        enc = _encrypt_password(plain)
        if enc:
            os.environ["TARASSUL_PASSWORD"] = plain
            lines = [l for l in lines if not _drop_line_if(l, ("TARASSUL_PASSWORD=", "TARASSUL_PASSWORD_ENC="))]
            lines.append(f"TARASSUL_PASSWORD_ENC={enc}")

    raw_tok = updates.get("NTFY_TOKEN")
    if raw_tok is not None and raw_tok != "" and raw_tok != "********":
        plain = sanitize(raw_tok)
        enc = _encrypt_password(plain)
        if enc:
            os.environ["NTFY_TOKEN"] = plain
            lines = [l for l in lines if not _drop_line_if(l, ("NTFY_TOKEN=", "NTFY_TOKEN_ENC="))]
            lines.append(f"NTFY_TOKEN_ENC={enc}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _get_config():
    def _mask(env_key: str) -> str:
        v = (os.environ.get(env_key) or "").strip()
        return "********" if v else ""
    def _schedule_enabled() -> bool:
        v = (os.environ.get("ENABLE_SCHEDULE") or "true").strip().lower()
        return v in ("true", "1", "yes")
    return {
        "telecom_base_url": (os.environ.get("TARASSUL_BASE_URL") or "").strip(),
        "telecom_fid": (os.environ.get("TARASSUL_FID") or "3").strip(),
        "telecom_username": (os.environ.get("TARASSUL_USERNAME") or "").strip(),
        "telecom_password": _mask("TARASSUL_PASSWORD"),
        "telecom_lang": (os.environ.get("TARASSUL_LANG") or "1").strip(),
        "schedule_enabled": _schedule_enabled(),
        "fetch_hour_2": (os.environ.get("FETCH_HOUR_2") or "20").strip(),
        "ntfy_url": (os.environ.get("NTFY_URL") or "").strip(),
        "ntfy_token": _mask("NTFY_TOKEN"),
        "theme": (os.environ.get("THEME") or "dark").strip().lower() or "dark",
    }


@app.before_request
def init_app():
    db.init_db()


@app.route("/")
def index():
    if not _has_admin_password():
        return redirect(url_for("set_initial_password_page"))
    try:
        verify_jwt_in_request(optional=True)
        if get_jwt_identity():
            return redirect(url_for("dashboard"))
    except Exception:
        pass
    return redirect(url_for("login"))


@app.context_processor
def inject_theme_and_admin():
    return {
        "theme": (os.environ.get("THEME") or "dark").strip().lower() or "dark",
        "admin_username": _admin_username(),
    }


@app.route("/set-initial-password", methods=["GET", "POST"])
def set_initial_password_page():
    if _has_admin_password():
        return redirect(url_for("login"))
    if request.method == "GET":
        return render_template("set_initial_password.html")
    password = (request.form.get("password") or "").strip()
    confirm = (request.form.get("confirm") or "").strip()
    if not password:
        return render_template("set_initial_password.html", error="Password is required"), 400
    if password != confirm:
        return render_template("set_initial_password.html", error="Passwords do not match"), 400
    if len(password) < 6:
        return render_template("set_initial_password.html", error="Use at least 6 characters"), 400
    username = _admin_username()
    _update_netmon_conf_admin(username, password)
    os.environ["ADMIN_PASSWORD"] = password  # so login works this request without reloading file
    return redirect(url_for("login", set=1))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not _has_admin_password():
        return redirect(url_for("set_initial_password_page"))
    if request.method == "GET":
        return render_template("login.html", password_set=request.args.get("set"))
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if username != _admin_username() or password != _admin_password():
        return render_template("login.html", error="Invalid credentials"), 401
    remember = request.form.get("remember") == "on"
    expires = timedelta(days=30) if remember else timedelta(days=1)
    token = create_access_token(identity=username, expires_delta=expires)
    resp = redirect(url_for("dashboard"))
    set_access_cookies(resp, token, max_age=int(expires.total_seconds()) if remember else None)
    return resp


@app.route("/logout", methods=["POST"])
def logout():
    resp = redirect(url_for("login"))
    unset_jwt_cookies(resp)
    return resp


@app.route("/dashboard")
@jwt_required()
def dashboard():
    return render_template("dashboard.html")


@app.route("/settings")
@jwt_required()
def settings_page():
    return render_template("settings.html")


@app.route("/records")
@jwt_required()
def records_page():
    page_size = 15
    try:
        page = int(request.args.get("page", "1") or "1")
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    offset = (page - 1) * page_size
    rows = db.get_all_fetches(limit=page_size, offset=offset)
    # Compute usage since the previous fetch (within this page, per product)
    for idx, row in enumerate(rows):
        delta_kb = None
        for j in range(idx + 1, len(rows)):
            other = rows[j]
            if other.get("product_id") == row.get("product_id"):
                try:
                    cur_kb = int(row.get("month_accu_volume_kb") or 0)
                    prev_kb = int(other.get("month_accu_volume_kb") or 0)
                except (TypeError, ValueError):
                    break
                diff = cur_kb - prev_kb
                if diff >= 0:
                    delta_kb = diff
                break
        if delta_kb is not None:
            row["usage_since_last_fetch_gb"] = round(delta_kb / (1024 * 1024), 2)
        else:
            row["usage_since_last_fetch_gb"] = None
    has_prev = page > 1
    has_next = len(rows) == page_size
    daily_usage = db.get_daily_usage(limit_days=31)
    return render_template(
        "records.html",
        records=rows,
        page=page,
        has_prev=has_prev,
        has_next=has_next,
        daily_usage=daily_usage,
    )


def _fetch_row_to_json(row: dict) -> dict:
    return {
        "id": row["id"],
        "fetched_at": row["fetched_at"],
        "product_id": row["product_id"],
        "product_name": row["product_name"],
        "month_accu_volume_kb": row["month_accu_volume_kb"],
        "max_service_usage_mb": row["max_service_usage_mb"],
        "usage_percent": row["usage_percent"],
        "exceed_day": row["exceed_day"],
        "month_begin": row["month_begin"],
        "month_end": row["month_end"],
    }


@app.route("/api/latest")
@jwt_required()
def api_latest():
    row = db.get_latest_fetch()
    if not row:
        return jsonify(None)
    return jsonify(_fetch_row_to_json(row))


@app.route("/api/history")
@jwt_required()
def api_history():
    month_begin = request.args.get("month_begin", "")
    if not month_begin:
        latest = db.get_latest_fetch()
        month_begin = (latest or {}).get("month_begin") or ""
    if not month_begin:
        return jsonify([])
    rows = db.get_history_for_month_baseline(month_begin)
    return jsonify([_fetch_row_to_json(r) for r in rows])


@app.route("/api/fetch", methods=["POST"])
@jwt_required()
def api_fetch():
    result = run_fetch()
    return jsonify(result)


@app.route("/api/settings", methods=["GET", "POST"])
@jwt_required()
def api_settings():
    if request.method == "GET":
        return jsonify(_get_config())
    data = request.get_json(force=True, silent=True) or {}
    key_to_field = {
        "telecom_base_url": "TARASSUL_BASE_URL",
        "telecom_fid": "TARASSUL_FID",
        "telecom_username": "TARASSUL_USERNAME",
        "telecom_password": "TARASSUL_PASSWORD",
        "telecom_lang": "TARASSUL_LANG",
        "schedule_enabled": "ENABLE_SCHEDULE",
        "fetch_hour_2": "FETCH_HOUR_2",
        "ntfy_url": "NTFY_URL",
        "ntfy_token": "NTFY_TOKEN",
        "theme": "THEME",
    }
    updates = {}
    for field, env_key in key_to_field.items():
        if field not in data:
            continue
        val = data[field]
        if env_key == "ENABLE_SCHEDULE":
            updates[env_key] = "true" if val in (True, "true", "1", "yes") else "false"
        elif isinstance(val, str):
            updates[env_key] = val
        elif val is not None and env_key not in ("TARASSUL_PASSWORD", "NTFY_TOKEN"):
            updates[env_key] = str(val).strip()
    try:
        _update_netmon_conf_settings(updates)
        scheduler_reschedule()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/settings/ntfy-test", methods=["POST"])
@jwt_required()
def api_settings_ntfy_test():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("ntfy_url") or "").strip() or (os.environ.get("NTFY_URL") or "").strip()
    token = (data.get("ntfy_token") or "").strip()
    if not token or token == "********":
        token = (os.environ.get("NTFY_TOKEN") or "").strip()
    result = send_ntfy_test(url, token)
    return jsonify(result)


@app.route("/api/settings/password", methods=["POST"])
@jwt_required()
def api_settings_password():
    data = request.get_json(force=True, silent=True) or {}
    new_password = (data.get("password") or "").strip()
    if not new_password:
        return jsonify({"ok": False, "error": "Password required"}), 400
    username = get_jwt_identity()
    if username != _admin_username():
        return jsonify({"ok": False, "error": "Only admin can change password"}), 403
    _update_netmon_conf_admin(username, new_password)
    os.environ["ADMIN_PASSWORD"] = new_password
    return jsonify({"ok": True})


def main():
    db.init_db()
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")


if __name__ == "__main__":
    main()
