"""Commercial ABET continuous-improvement platform."""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from flask import Flask, g, render_template, session

from . import db
from .security import (
    csrf_token,
    enforce_password_change,
    load_faculty_preview,
    load_identity,
    protect_csrf,
)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    production = os.getenv("ABET_ENV", "development").lower() == "production"
    secret = os.getenv("ABET_SECRET_KEY")
    if production and not secret:
        raise RuntimeError("ABET_SECRET_KEY must be set in production")
    setup_token = os.getenv("ABET_SETUP_TOKEN")
    if production and not setup_token:
        raise RuntimeError("ABET_SETUP_TOKEN must be set in production")

    app.config.from_mapping(
        SECRET_KEY=secret or secrets.token_hex(32),
        DATABASE=os.getenv("ABET_DATABASE", str(Path(app.instance_path) / "abet_platform.db")),
        UPLOAD_FOLDER=os.getenv("ABET_UPLOAD_FOLDER", str(Path(app.instance_path) / "uploads")),
        MAX_CONTENT_LENGTH=int(os.getenv("ABET_MAX_UPLOAD_MB", "25")) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
        EDITION="generic",
        PRODUCT_NAME="AccreditationOS",
        CUSTOMER_NAME="",
        LEGACY_DATABASE=os.getenv("UTRGV_LEGACY_ABET_DB", ""),
        LEGACY_SOURCES={},
        SETUP_TOKEN=setup_token or "",
        MATPLOTLIB_CONFIG_DIR=os.getenv(
            "MPLCONFIGDIR", str(Path(app.instance_path) / "matplotlib")
        ),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["MATPLOTLIB_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", app.config["MATPLOTLIB_CONFIG_DIR"])

    db.init_app(app)

    from .routes import bp

    app.register_blueprint(bp)
    app.before_request(load_identity)
    app.before_request(load_faculty_preview)
    app.before_request(enforce_password_change)
    app.before_request(protect_csrf)

    @app.context_processor
    def inject_globals():
        program = None
        organization = None
        if getattr(g, "user", None) and session.get("program_id"):
            organization = db.get_db().execute(
                "SELECT id, name, primary_color, accent_color FROM organizations WHERE id = ?",
                (session.get("organization_id"),),
            ).fetchone()
            program = db.get_db().execute(
                "SELECT id, code, name FROM programs WHERE id = ? AND organization_id = ?",
                (session["program_id"], session.get("organization_id")),
            ).fetchone()
        brand_style = ""
        if organization:
            primary, accent = organization["primary_color"], organization["accent_color"]
            if re.fullmatch(r"#[0-9a-fA-F]{6}", primary) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
                brand_style = f"--navy:{primary};--navy-2:{primary};--orange:{accent}"
        return {
            "csrf_token": csrf_token,
            "current_program": program,
            "current_organization": organization,
            "brand_style": brand_style,
        }

    @app.after_request
    def secure_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'self'",
        )
        if getattr(g, "user", None):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def handled_error(error):
        messages = {
            400: "The request could not be completed.",
            403: "You do not have access to this area.",
            404: "The requested page was not found.",
            413: "That file is larger than the configured upload limit.",
        }
        return render_template(
            "error.html", code=error.code, message=getattr(error, "description", messages[error.code])
        ), error.code

    return app
