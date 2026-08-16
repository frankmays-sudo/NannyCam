#!/usr/bin/env python3
"""NannyCam footage GUI entry point.

Reads config/settings.yaml and serves a small Flask app for browsing,
downloading, and deleting recorded footage segments. Runs as a separate
process/systemd unit from main.py — it only touches the filesystem under
recording.segment_dir, never the camera or GPIO.
"""

import hashlib
import hmac
import logging
import re
from datetime import datetime
from functools import wraps
from pathlib import Path

import yaml
from flask import Flask, Response, abort, redirect, render_template, request, send_from_directory, url_for

from src.storage.ring import list_segments

logger = logging.getLogger(__name__)

# Matches recorder.py's f"{ts}_%04d.h264" pattern, e.g. 20260816_143012_0000.h264
_SEGMENT_NAME_RE = re.compile(r"^\d{8}_\d{6}_\d{4}\.h264$")


def _check_password(password: str, stored_hash: str) -> bool:
    candidate = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(candidate, stored_hash)


def create_app(config: dict) -> Flask:
    app = Flask(__name__)
    app.config["SEGMENT_DIR"] = Path(config["recording"]["segment_dir"])
    app.config["GUI_PASSWORD_HASH"] = config["gui"]["password_hash"]

    @app.template_filter("datetimeformat")
    def datetimeformat(mtime: float) -> str:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    def requires_auth(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.authorization
            if not auth or not _check_password(auth.password, app.config["GUI_PASSWORD_HASH"]):
                return Response(
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="NannyCam"'},
                )
            return view(*args, **kwargs)

        return wrapped

    def _validate_filename(filename: str) -> str:
        if not _SEGMENT_NAME_RE.fullmatch(filename):
            abort(404)
        segment_dir = app.config["SEGMENT_DIR"].resolve()
        resolved = (segment_dir / filename).resolve()
        if resolved.parent != segment_dir:
            abort(404)
        return filename

    @app.route("/")
    @requires_auth
    def index():
        segments = list_segments(app.config["SEGMENT_DIR"])
        segments = sorted(segments, key=lambda s: s.mtime, reverse=True)
        return render_template("index.html", segments=segments)

    @app.route("/download/<path:filename>")
    @requires_auth
    def download(filename):
        safe_name = _validate_filename(filename)
        return send_from_directory(app.config["SEGMENT_DIR"], safe_name, as_attachment=True)

    @app.route("/delete/<path:filename>", methods=["POST"])
    @requires_auth
    def delete(filename):
        safe_name = _validate_filename(filename)
        (app.config["SEGMENT_DIR"] / safe_name).unlink(missing_ok=True)
        logger.info("Deleted segment %s via GUI", safe_name)
        return redirect(url_for("index"))

    return app


def _load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = _load_config(Path(__file__).parent.parent.parent / "config" / "settings.yaml")
    g = cfg["gui"]

    app = create_app(cfg)
    app.run(host=g["host"], port=g["port"])


if __name__ == "__main__":
    main()
