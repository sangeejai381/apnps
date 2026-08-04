from datetime import datetime
from functools import wraps

from flask import redirect, request, session, url_for
from sqlalchemy import func, inspect, text

from extensions import db
from models import Admin, Student, StudentFee, StudentFeeItem
from constants import PAGE_SIZE


def login_required(f):
    """Redirects to the login page unless an admin is signed in."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def get_page_arg():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    return max(page, 1)


def paginate(query, page=None):
    return query.paginate(page=page or get_page_arg(), per_page=PAGE_SIZE, error_out=False)


def current_academic_year():
    """India's school year runs Apr-Mar. Returns e.g. "2026-27"."""
    today = datetime.now()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def previous_academic_year(year_str):
    """"2026-27" -> "2025-26". None if year_str isn't "YYYY-YY" shaped."""
    try:
        start_year = int((year_str or "").split("-")[0])
    except (ValueError, IndexError):
        return None
    prev_start = start_year - 1
    return f"{prev_start}-{str(prev_start + 1)[-2:]}"


def recompute_student_fee_total(student, academic_year):
    """
    Recalculates the cached StudentFee.total_fee/academic_year for one
    student from their actual StudentFeeItem rows for that year. Does not
    commit — caller commits once, alongside whatever item change triggered
    the recompute.
    """
    total = (
        db.session.query(func.coalesce(func.sum(StudentFeeItem.amount), 0))
        .filter(StudentFeeItem.student_id == student.id, StudentFeeItem.academic_year == academic_year)
        .scalar()
    )
    if not student.fee:
        student.fee = StudentFee(student_id=student.id, total_fee=0)
        db.session.add(student.fee)
    student.fee.total_fee = total
    student.fee.academic_year = academic_year


def seed_admin():
    """Ensures an admin login exists; migrates a known old default email."""
    known_previous_emails = {"admin@apnps.edu.in"}
    current_email = "annaiparvatham.jkpm@gmail.com"

    admin = Admin.query.first()
    if not admin:
        db.session.add(Admin(email=current_email, pin="apnps@2026", name="School Admin"))
        db.session.commit()
    elif admin.email in known_previous_emails and admin.email != current_email:
        admin.email = current_email
        db.session.commit()


def ensure_schema_migrations():
    """
    Idempotent column migrations for model changes made after first deploy.
    db.create_all() only creates missing tables, never alters existing
    ones — safe to run on every startup.
    """
    inspector = inspect(db.engine)
    if "student" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("student")}
        for col, ddl in (
            ("address", "ALTER TABLE student ADD COLUMN address VARCHAR(250)"),
            ("section", "ALTER TABLE student ADD COLUMN section VARCHAR(10)"),
            ("dob", "ALTER TABLE student ADD COLUMN dob VARCHAR(20)"),
        ):
            if col not in existing_columns:
                with db.engine.begin() as conn:
                    conn.execute(text(ddl))

    if "student_fee" in inspector.get_table_names():
        existing_fee_columns = {col["name"] for col in inspector.get_columns("student_fee")}
        if "academic_year" not in existing_fee_columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE student_fee ADD COLUMN academic_year VARCHAR(20)"))

    if "fee_payment" in inspector.get_table_names():
        existing_payment_columns = {col["name"] for col in inspector.get_columns("fee_payment")}
        if "fee_item_id" not in existing_payment_columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE fee_payment ADD COLUMN fee_item_id INTEGER"))


def backfill_legacy_fee_items():
    """
    One-time (idempotent) migration: any student with an old flat
    StudentFee.total_fee but no StudentFeeItem rows yet gets a single
    "Tuition Fee" item for the current academic year matching that amount.
    """
    year = current_academic_year()
    candidates = (
        Student.query.join(StudentFee)
        .filter(StudentFee.total_fee > 0)
        .filter(~Student.fee_items.any())
        .all()
    )
    for student in candidates:
        db.session.add(StudentFeeItem(
            student_id=student.id, academic_year=year,
            category="Tuition Fee", custom_category="", amount=student.fee.total_fee,
        ))
        student.fee.academic_year = year
    if candidates:
        db.session.commit()
