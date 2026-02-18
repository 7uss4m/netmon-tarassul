"""
Flask app: JWT login, dashboard, API for latest/history/settings/fetch.
"""
import os
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
from fetcher import run_fetch
from scheduler import start_scheduler, reschedule

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "change-me-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

jwt = JWTManager(app)


def _admin_username():
    return (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"


@app.before_request
def init_app():
    db.init_db()


@app.route("/")
def index():
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if username != _admin_username():
        return render_template("login.html", error="Invalid credentials"), 401
    if not db.verify_password(password):
        return render_template("login.html", error="Invalid credentials"), 401
    token = create_access_token(identity=username)
    resp = redirect(url_for("dashboard"))
    set_access_cookies(resp, token)
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


@app.route("/api/latest")
@jwt_required()
def api_latest():
    row = db.get_latest_fetch()
    if not row:
        return jsonify(None)
    return jsonify({
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
    })


@app.route("/api/history")
@jwt_required()
def api_history():
    month_begin = request.args.get("month_begin", "")
    if not month_begin:
        latest = db.get_latest_fetch()
        month_begin = (latest or {}).get("month_begin") or ""
    if not month_begin:
        return jsonify([])
    rows = db.get_history_for_month(month_begin)
    return jsonify([
        {
            "id": r["id"],
            "fetched_at": r["fetched_at"],
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "month_accu_volume_kb": r["month_accu_volume_kb"],
            "max_service_usage_mb": r["max_service_usage_mb"],
            "usage_percent": r["usage_percent"],
            "exceed_day": r["exceed_day"],
            "month_begin": r["month_begin"],
            "month_end": r["month_end"],
        }
        for r in rows
    ])


@app.route("/api/fetch", methods=["POST"])
@jwt_required()
def api_fetch():
    result = run_fetch()
    return jsonify(result)


@app.route("/api/settings", methods=["GET", "POST"])
@jwt_required()
def api_settings():
    if request.method == "GET":
        return jsonify(db.get_all_settings())
    data = request.get_json(force=True, silent=True) or {}
    allowed = {
        "telecom_base_url", "telecom_fid", "telecom_username", "telecom_password",
        "telecom_lang", "fetch_hour_1", "fetch_hour_2", "ntfy_url",
    }
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if updates:
        db.set_settings(updates)
        reschedule()
    return jsonify(db.get_all_settings())


@app.route("/api/settings/password", methods=["POST"])
@jwt_required()
def api_settings_password():
    data = request.get_json(force=True, silent=True) or {}
    new_password = (data.get("password") or "").strip()
    if not new_password:
        return jsonify({"ok": False, "error": "Password required"}), 400
    db.set_dashboard_password(new_password)
    return jsonify({"ok": True})


def main():
    db.init_db()
    if os.environ.get("ADMIN_PASSWORD"):
        db.set_dashboard_password(os.environ.get("ADMIN_PASSWORD"))
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")


if __name__ == "__main__":
    main()
