from datetime import datetime
from functools import wraps

from flask import redirect, request, session, url_for
from sqlalchemy import func, inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import Admin, FeeStructure, Student, StudentFee, StudentFeeItem
from constants import CONCESSION_CATEGORY, PAGE_SIZE


def login_required(f):
    """Redirects to the admin login page unless an admin is signed in."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def teacher_login_required(f):
    """Redirects to the teacher login page unless a teacher is signed in.
    Kept entirely separate from admin's login_required — an admin session
    does not grant teacher-portal access and vice versa (RBAC: two
    distinct identities, not one shared login)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "teacher_id" not in session:
            return redirect(url_for("teacher_portal.login"))
        return f(*args, **kwargs)
    return wrapper


def set_teacher_password(teacher, raw_password):
    teacher.password_hash = generate_password_hash(raw_password)


def verify_teacher_password(teacher, raw_password):
    if not teacher.password_hash:
        return False
    return check_password_hash(teacher.password_hash, raw_password)


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


def sync_students_without_fee_items(class_name, academic_year):
    """
    Applies the current class Fee Structure to students in that class who
    haven't customized their fee away from it — covers the common workflow
    of enrolling students first and setting up (or still building, one
    category at a time) the year's fee structure afterward, without
    needing to open every single student and click "Reset to Class
    Structure" one by one.

    A student is eligible if every fee item they already have (ignoring
    Concession/Discount lines, which are never part of a class structure)
    both belongs to the current structure AND still matches its amount
    exactly — i.e. nothing about their fee has been manually customized.
    Only the categories they're missing get added; categories they already
    have are left alone. Any student whose fee has diverged even slightly
    (a different amount, or an extra category not in the structure) is
    skipped entirely, so this can never silently overwrite something an
    admin already configured or a student has already made payments
    against. Those students still have the manual "Reset to Class
    Structure" button on their own Fee Detail page.
    """
    structure_rows = FeeStructure.query.filter_by(class_name=class_name, academic_year=academic_year).all()
    if not structure_rows:
        return 0
    structure_by_key = {(r.category, r.custom_category): r.amount for r in structure_rows}

    students = Student.query.filter_by(class_name=class_name).all()
    synced = 0
    for student in students:
        existing_items = StudentFeeItem.query.filter_by(student_id=student.id, academic_year=academic_year).all()
        existing_fee_items = [i for i in existing_items if i.category != CONCESSION_CATEGORY]

        if existing_fee_items:
            still_matches_structure = all(
                (i.category, i.custom_category) in structure_by_key
                and i.amount == structure_by_key[(i.category, i.custom_category)]
                for i in existing_fee_items
            )
            if not still_matches_structure:
                continue
            existing_keys = {(i.category, i.custom_category) for i in existing_fee_items}
        else:
            existing_keys = set()

        missing_rows = [row for row in structure_rows if (row.category, row.custom_category) not in existing_keys]
        if not missing_rows:
            continue

        for row in missing_rows:
            db.session.add(StudentFeeItem(
                student_id=student.id, academic_year=academic_year,
                category=row.category, custom_category=row.custom_category, amount=row.amount,
            ))
        recompute_student_fee_total(student, current_academic_year())
        synced += 1

    if synced:
        db.session.commit()
    return synced


def seed_admin():
    """Ensures an admin login exists; migrates a known old default email."""
    known_previous_emails = {"admin@apnps.edu.in"}
    current_email = "annaiparvatham.jkpm@gmail.com"

    admin = Admin.query.first()
    if not admin:
        db.session.add(Admin(email=current_email, pin=generate_password_hash("apnps@2026"), name="School Admin"))
        db.session.commit()
    elif admin.email in known_previous_emails and admin.email != current_email:
        admin.email = current_email
        db.session.commit()


def _looks_hashed(value):
    """werkzeug hashes are always 'method:salt:hash' or similar — a real
    PIN like 'apnps@2026' or a 4-6 digit PIN never contains a colon."""
    return isinstance(value, str) and ":" in value and len(value) > 20


def upgrade_legacy_admin_pins():
    """
    One-time, idempotent migration: any Admin row still storing a plaintext
    PIN (from before PIN hashing was added) gets it hashed in place. Safe to
    run on every startup — already-hashed PINs are left untouched.
    """
    legacy_admins = [a for a in Admin.query.all() if not _looks_hashed(a.pin)]
    if not legacy_admins:
        return
    for admin in legacy_admins:
        admin.pin = generate_password_hash(admin.pin)
    db.session.commit()


def verify_admin_pin(admin, raw_pin):
    """Constant-time-ish check against the stored hash (handles the brief
    window where a legacy plaintext PIN hasn't been migrated yet)."""
    if _looks_hashed(admin.pin):
        return check_password_hash(admin.pin, raw_pin)
    return admin.pin == raw_pin


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

    if "admin" in inspector.get_table_names() and db.engine.dialect.name == "postgresql":
        # SQLite ignores VARCHAR length entirely, so this only matters for
        # Postgres deployments — widen pin to fit a password hash (was
        # sized for a short plaintext PIN before hashing was added).
        pin_column = next((c for c in inspector.get_columns("admin") if c["name"] == "pin"), None)
        if pin_column and getattr(pin_column["type"], "length", None) and pin_column["type"].length < 255:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE admin ALTER COLUMN pin TYPE VARCHAR(255)"))

    if "teacher" in inspector.get_table_names():
        existing_teacher_columns = {col["name"] for col in inspector.get_columns("teacher")}
        teacher_portal_columns = {
            "email": "VARCHAR(120)",
            "password_hash": "VARCHAR(255)",
            "assigned_class": "VARCHAR(40)",
            "assigned_section": "VARCHAR(10)",
            "portal_active": "BOOLEAN DEFAULT FALSE",
        }
        for col_name, col_type in teacher_portal_columns.items():
            if col_name not in existing_teacher_columns:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE teacher ADD COLUMN {col_name} {col_type}"))


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
