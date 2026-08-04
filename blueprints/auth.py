from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

from extensions import db
from models import Admin, LoginAttempt
from constants import MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        pin = request.form.get("pin", "").strip()

        if not identifier or not pin:
            flash("Please enter both an email/mobile number and a PIN.")
            return redirect(url_for("auth.login"))

        now = datetime.utcnow()
        attempt = LoginAttempt.query.filter_by(identifier=identifier).first()

        if attempt and attempt.locked_until and attempt.locked_until > now:
            remaining_seconds = (attempt.locked_until - now).total_seconds()
            remaining_minutes = max(1, int(remaining_seconds // 60) + (1 if remaining_seconds % 60 else 0))
            flash(f"Too many failed attempts. This login is locked for {remaining_minutes} more minute(s).")
            return redirect(url_for("auth.login"))

        admin = Admin.query.filter(func.lower(Admin.email) == identifier).first()

        if admin and admin.pin == pin:
            if attempt:
                attempt.failed_count = 0
                attempt.locked_until = None
                db.session.commit()
            session["admin_id"] = admin.id
            session["admin_name"] = admin.name
            return redirect(url_for("dashboard.dashboard"))

        if not attempt:
            attempt = LoginAttempt(identifier=identifier, failed_count=0)
            db.session.add(attempt)

        attempt.failed_count += 1
        if attempt.failed_count >= MAX_LOGIN_ATTEMPTS:
            attempt.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            attempt.failed_count = 0
            db.session.commit()
            flash(f"Too many failed attempts. This login is locked for {LOCKOUT_MINUTES} minutes.")
        else:
            db.session.commit()
            remaining_tries = MAX_LOGIN_ATTEMPTS - attempt.failed_count
            flash(f"Invalid email/mobile or PIN. {remaining_tries} attempt(s) remaining before a temporary lock.")
        return redirect(url_for("auth.login"))

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
