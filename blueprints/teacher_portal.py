from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

from extensions import db
from models import FeePayment, LoginAttempt, Message, Student, StudentFee, Teacher
from constants import LOCKOUT_MINUTES, MAX_LOGIN_ATTEMPTS
from helpers import set_teacher_password, teacher_login_required, verify_teacher_password

bp = Blueprint("teacher_portal", __name__, url_prefix="/teacher")

# LoginAttempt.identifier is shared with the admin login table — namespace
# teacher lockout entries so a teacher and an admin could never share/clash
# on the same identifier string.
def _lockout_key(email):
    return f"teacher:{email}"


def _current_teacher():
    return Teacher.query.get(session.get("teacher_id"))


def _class_label(teacher):
    if not teacher.assigned_class:
        return "No class assigned yet"
    return teacher.assigned_class + (f" {teacher.assigned_section}" if teacher.assigned_section else "")


def _student_fee_rows(teacher):
    """Per-student (student, total_fee, paid, balance) for this teacher's assigned class/section."""
    if not teacher.assigned_class:
        return []
    paid_subq = (
        db.session.query(FeePayment.student_id.label("student_id"), func.sum(FeePayment.amount).label("paid"))
        .group_by(FeePayment.student_id).subquery()
    )
    query = (
        db.session.query(Student, func.coalesce(StudentFee.total_fee, 0), func.coalesce(paid_subq.c.paid, 0))
        .outerjoin(StudentFee, StudentFee.student_id == Student.id)
        .outerjoin(paid_subq, paid_subq.c.student_id == Student.id)
        .filter(Student.class_name == teacher.assigned_class)
    )
    if teacher.assigned_section:
        query = query.filter(Student.section == teacher.assigned_section)
    query = query.order_by(Student.name)

    rows = []
    for student, total, paid in query.all():
        balance = total - paid
        status = (
            "Paid" if balance <= 0 and total > 0
            else ("Not Set" if total == 0 else ("Partial" if paid > 0 else "Due"))
        )
        rows.append({"student": student, "total": total, "paid": paid, "balance": balance, "status": status})
    return rows


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Please enter both your email and password.")
            return redirect(url_for("teacher_portal.login"))

        now = datetime.utcnow()
        lockout_id = _lockout_key(email)
        attempt = LoginAttempt.query.filter_by(identifier=lockout_id).first()

        if attempt and attempt.locked_until and attempt.locked_until > now:
            remaining_seconds = (attempt.locked_until - now).total_seconds()
            remaining_minutes = max(1, int(remaining_seconds // 60) + (1 if remaining_seconds % 60 else 0))
            flash(f"Too many failed attempts. This login is locked for {remaining_minutes} more minute(s).")
            return redirect(url_for("teacher_portal.login"))

        teacher = Teacher.query.filter(func.lower(Teacher.email) == email).first()
        valid = teacher and teacher.portal_active and verify_teacher_password(teacher, password)

        if valid:
            if attempt:
                attempt.failed_count = 0
                attempt.locked_until = None
                db.session.commit()
            session.clear()
            session.permanent = True
            session["teacher_id"] = teacher.id
            session["teacher_name"] = teacher.name
            return redirect(url_for("teacher_portal.dashboard"))

        if not attempt:
            attempt = LoginAttempt(identifier=lockout_id, failed_count=0)
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
            if teacher and not teacher.portal_active:
                flash("This account doesn't have portal access enabled yet — ask your school admin to activate it.")
            else:
                flash(f"Invalid email or password. {remaining_tries} attempt(s) remaining before a temporary lock.")
        return redirect(url_for("teacher_portal.login"))

    return render_template("teacher_login.html")


@bp.route("/logout")
def logout():
    session.pop("teacher_id", None)
    session.pop("teacher_name", None)
    return redirect(url_for("teacher_portal.login"))


@bp.route("/dashboard")
@teacher_login_required
def dashboard():
    teacher = _current_teacher()
    if not teacher:
        return redirect(url_for("teacher_portal.logout"))

    class_label = _class_label(teacher)
    rows = _student_fee_rows(teacher)
    today = datetime.now().strftime("%Y-%m-%d")

    total_students = len(rows)
    pending_count = sum(1 for r in rows if r["balance"] > 0)

    paid_today_count = 0
    upcoming_due = []
    if teacher.assigned_class:
        student_ids = [r["student"].id for r in rows]
        if student_ids:
            paid_today_count = (
                db.session.query(func.count(func.distinct(FeePayment.student_id)))
                .filter(FeePayment.student_id.in_(student_ids), FeePayment.date == today).scalar()
            )
        due_rows = [r for r in rows if r["balance"] > 0 and r["student"].fee and r["student"].fee.due_date]
        due_rows.sort(key=lambda r: r["student"].fee.due_date)
        upcoming_due = due_rows[:5]

    recent_notifications = Message.query.order_by(Message.posted_at.desc()).limit(5).all()

    return render_template(
        "teacher_dashboard.html", teacher=teacher, class_label=class_label,
        total_students=total_students, pending_count=pending_count, paid_today_count=paid_today_count,
        upcoming_due=upcoming_due, recent_notifications=recent_notifications,
    )


@bp.route("/students")
@teacher_login_required
def my_students():
    teacher = _current_teacher()
    if not teacher:
        return redirect(url_for("teacher_portal.logout"))
    class_label = _class_label(teacher)
    rows = _student_fee_rows(teacher)
    return render_template("teacher_students.html", teacher=teacher, class_label=class_label, rows=rows)


@bp.route("/change-password", methods=["GET", "POST"])
@teacher_login_required
def change_password():
    teacher = _current_teacher()
    if not teacher:
        return redirect(url_for("teacher_portal.logout"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not verify_teacher_password(teacher, current_password):
            flash("Your current password is incorrect.")
        elif len(new_password) < 6:
            flash("New password must be at least 6 characters.")
        elif new_password != confirm_password:
            flash("New password and confirmation don't match.")
        else:
            set_teacher_password(teacher, new_password)
            db.session.commit()
            flash("Password updated.")
            return redirect(url_for("teacher_portal.dashboard"))
        return redirect(url_for("teacher_portal.change_password"))

    return render_template("teacher_change_password.html", teacher=teacher)
