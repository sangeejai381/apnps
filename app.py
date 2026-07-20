import csv
import io
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response,
)
from flask_wtf import CSRFProtect
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from models import (
    db, Admin, LoginAttempt, Student, StudentFee, FeePayment,
    Teacher, TeacherSalary, SalaryPayment, Expense,
)
from constants import (
    CLASS_CHOICES, PAGE_SIZE, MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES,
    CSV_IMPORT_COLUMNS, EXPENSE_CATEGORIES,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "apnps-admin-secret-key-change-me")

basedir = os.path.abspath(os.path.dirname(__file__))


def normalize_database_url(url):
 
    if not url:
        return None
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url

default_db_uri = "sqlite:///" + os.path.join(basedir, "school.db")
raw_database_url = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_url(raw_database_url) or default_db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,  
    "pool_recycle": 300,    
                             
}
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 

db.init_app(app)

csrf = CSRFProtect(app)

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="That page doesn't exist."), 404

@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template("error.html", code=500, message="Something went wrong on our end. Your last action may not have been saved — please try again."), 500

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def seed_admin():
    if not Admin.query.first():
        db.session.add(Admin(email="admin@apnps.edu.in", pin="apnps@2026", name="School Admin"))
        db.session.commit()


def get_page_arg():
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    return max(page, 1)


@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        pin = request.form.get("pin", "").strip()

        if not identifier or not pin:
            flash("Please enter both an email/mobile number and a PIN.")
            return redirect(url_for("login"))

        now = datetime.utcnow()
        attempt = LoginAttempt.query.filter_by(identifier=identifier).first()

        if attempt and attempt.locked_until and attempt.locked_until > now:
            remaining_seconds = (attempt.locked_until - now).total_seconds()
            remaining_minutes = max(1, int(remaining_seconds // 60) + (1 if remaining_seconds % 60 else 0))
            flash(f"Too many failed attempts. This login is locked for {remaining_minutes} more minute(s).")
            return redirect(url_for("login"))

        admin = Admin.query.filter(func.lower(Admin.email) == identifier).first()

        if admin and admin.pin == pin:
            if attempt:
                attempt.failed_count = 0
                attempt.locked_until = None
                db.session.commit()
            session["admin_id"] = admin.id
            session["admin_name"] = admin.name
            return redirect(url_for("dashboard"))

    
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
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    total_students = Student.query.count()
    total_teachers = Teacher.query.count()

    total_fee_expected = db.session.query(func.coalesce(func.sum(StudentFee.total_fee), 0)).scalar()
    total_fee_collected = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).scalar()
    total_fee_due = total_fee_expected - total_fee_collected

    total_salary_expected = db.session.query(func.coalesce(func.sum(TeacherSalary.monthly_salary), 0)).scalar()
    total_salary_paid = db.session.query(func.coalesce(func.sum(SalaryPayment.amount), 0)).scalar()
    total_salary_due = total_salary_expected - total_salary_paid

    total_expenses = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar()

    recent_payments = FeePayment.query.order_by(FeePayment.id.desc()).limit(5).all()
    recent_expenses = Expense.query.order_by(Expense.id.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        total_teachers=total_teachers,
        total_fee_expected=total_fee_expected,
        total_fee_collected=total_fee_collected,
        total_fee_due=total_fee_due,
        total_salary_expected=total_salary_expected,
        total_salary_paid=total_salary_paid,
        total_salary_due=total_salary_due,
        total_expenses=total_expenses,
        recent_payments=recent_payments,
        recent_expenses=recent_expenses,
    )

@app.route("/students")
@login_required
def students():
    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    page = get_page_arg()

    query = Student.query
    if class_filter and class_filter in CLASS_CHOICES:
        query = query.filter(Student.class_name == class_filter)
    if q:
       
        query = query.filter(db.or_(Student.name.ilike(f"%{q}%"), Student.roll_no.ilike(f"%{q}%")))

    total_matching = query.count()
  
    pagination = query.order_by(Student.class_name, Student.name).paginate(
        page=page, per_page=PAGE_SIZE, error_out=False
    )

    return render_template(
        "students.html",
        students=pagination.items,
        pagination=pagination,
        total_matching=total_matching,
        q=q,
        class_filter=class_filter,
        class_choices=CLASS_CHOICES,
    )


@app.route("/students/add", methods=["GET", "POST"])
@login_required
def add_student():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        roll_no = request.form.get("roll_no", "").strip()

        if not name or not class_name or not roll_no:
            flash("Name, class, and roll number are required.")
            return redirect(url_for("add_student"))

        if class_name not in CLASS_CHOICES:
            flash("Please choose a class from the list.")
            return redirect(url_for("add_student"))

        try:
            total_fee = float(request.form.get("total_fee") or 0)
        except ValueError:
            flash("Total fee must be a number.")
            return redirect(url_for("add_student"))
        if total_fee < 0:
            flash("Total fee cannot be negative.")
            return redirect(url_for("add_student"))

        existing = Student.query.filter_by(class_name=class_name, roll_no=roll_no).first()
        if existing:
            flash(f"A student with roll number {roll_no} already exists in {class_name}.")
            return redirect(url_for("add_student"))

        try:
            s = Student(
                name=name,
                class_name=class_name,
                roll_no=roll_no,
                parent_name=request.form.get("parent_name", "").strip(),
                contact=request.form.get("contact", "").strip(),
                admission_date=request.form.get("admission_date", "").strip(),
            )
            db.session.add(s)
            db.session.flush()
            fee = StudentFee(
                student_id=s.id,
                total_fee=total_fee,
                due_date=request.form.get("due_date", "").strip(),
            )
            db.session.add(fee)
            db.session.commit()
            flash(f"Student {s.name} added successfully.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this student. Please try again.")
        return redirect(url_for("students"))
    return render_template("add_student.html", class_choices=CLASS_CHOICES)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    s = Student.query.get_or_404(student_id)
    db.session.delete(s)
    db.session.commit()
    flash("Student record deleted.")
    return redirect(url_for("students"))

@app.route("/students/import/template")
@login_required
def download_import_template():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_IMPORT_COLUMNS)
    writer.writerow(["Kavya R", "UKG", "12", "Ramesh R", "9876543210", "2024-06-03", "18000", "2024-07-15"])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=apnps_student_import_template.csv"},
    )


@app.route("/students/import", methods=["GET", "POST"])
@login_required
def import_students():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose a CSV file to upload.")
            return redirect(url_for("import_students"))
        if not file.filename.lower().endswith(".csv"):
            flash("Please upload a .csv file.")
            return redirect(url_for("import_students"))

        try:
            raw = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("Could not read that file. Please save it as a standard CSV (UTF-8) and try again.")
            return redirect(url_for("import_students"))

        reader = csv.DictReader(io.StringIO(raw))
        missing_cols = [c for c in ("name", "class_name", "roll_no") if c not in (reader.fieldnames or [])]
        if missing_cols:
            flash(f"The CSV is missing required column(s): {', '.join(missing_cols)}. Download the template below to see the expected format.")
            return redirect(url_for("import_students"))

        created = 0
        errors = []
        seen_in_file = set()

        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            name = (row.get("name") or "").strip()
            class_name = (row.get("class_name") or "").strip()
            roll_no = (row.get("roll_no") or "").strip()

            if not name or not class_name or not roll_no:
                errors.append(f"Row {row_num}: name, class, and roll number are required — skipped.")
                continue
            if class_name not in CLASS_CHOICES:
                errors.append(f"Row {row_num}: '{class_name}' is not a valid class ({', '.join(CLASS_CHOICES)}) — skipped.")
                continue

            key = (class_name, roll_no)
            if key in seen_in_file:
                errors.append(f"Row {row_num}: roll number {roll_no} in {class_name} is duplicated within this file — skipped.")
                continue
            if Student.query.filter_by(class_name=class_name, roll_no=roll_no).first():
                errors.append(f"Row {row_num}: roll number {roll_no} in {class_name} already exists — skipped.")
                continue

            total_fee_raw = (row.get("total_fee") or "0").strip()
            try:
                total_fee = float(total_fee_raw) if total_fee_raw else 0.0
                if total_fee < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Row {row_num}: total_fee '{total_fee_raw}' is not a valid non-negative number — skipped.")
                continue

            seen_in_file.add(key)
            s = Student(
                name=name,
                class_name=class_name,
                roll_no=roll_no,
                parent_name=(row.get("parent_name") or "").strip(),
                contact=(row.get("contact") or "").strip(),
                admission_date=(row.get("admission_date") or "").strip(),
            )
            db.session.add(s)
            db.session.flush()
            db.session.add(StudentFee(
                student_id=s.id,
                total_fee=total_fee,
                due_date=(row.get("due_date") or "").strip(),
            ))
            created += 1

        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            flash("Something went wrong saving the import. No rows were added — please try again.")
            return redirect(url_for("import_students"))

        if created:
            flash(f"Imported {created} student(s) successfully.")
        if errors:
            flash(f"{len(errors)} row(s) were skipped — see details below.")

        return render_template(
            "import_students.html",
            class_choices=CLASS_CHOICES,
            import_errors=errors,
            created_count=created,
        )

    return render_template("import_students.html", class_choices=CLASS_CHOICES, import_errors=None, created_count=None)


@app.route("/fees")
@login_required
def fees():
    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()
    page = get_page_arg()

    paid_subq = (
        db.session.query(
            FeePayment.student_id.label("student_id"),
            func.sum(FeePayment.amount).label("paid"),
        )
        .group_by(FeePayment.student_id)
        .subquery()
    )

    query = (
        db.session.query(
            Student,
            func.coalesce(StudentFee.total_fee, 0).label("total"),
            func.coalesce(paid_subq.c.paid, 0).label("paid"),
        )
        .outerjoin(StudentFee, StudentFee.student_id == Student.id)
        .outerjoin(paid_subq, paid_subq.c.student_id == Student.id)
    )
    if class_filter and class_filter in CLASS_CHOICES:
        query = query.filter(Student.class_name == class_filter)
    if q:
        query = query.filter(db.or_(Student.name.ilike(f"%{q}%"), Student.roll_no.ilike(f"%{q}%")))

    query = query.order_by(Student.class_name, Student.name)
    pagination = query.paginate(page=page, per_page=PAGE_SIZE, error_out=False)

    rows = []
    for s, total, paid in pagination.items:
        balance = total - paid
        status = "Paid" if balance <= 0 and total > 0 else ("Not Set" if total == 0 else ("Partial" if paid > 0 else "Due"))
        rows.append({"student": s, "total": total, "paid": paid, "balance": balance, "status": status})

    expected_q = db.session.query(func.coalesce(func.sum(StudentFee.total_fee), 0)).join(
        Student, Student.id == StudentFee.student_id
    )
    collected_q = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).join(
        Student, Student.id == FeePayment.student_id
    )
    if class_filter and class_filter in CLASS_CHOICES:
        expected_q = expected_q.filter(Student.class_name == class_filter)
        collected_q = collected_q.filter(Student.class_name == class_filter)
    if q:
        name_or_roll = db.or_(Student.name.ilike(f"%{q}%"), Student.roll_no.ilike(f"%{q}%"))
        expected_q = expected_q.filter(name_or_roll)
        collected_q = collected_q.filter(name_or_roll)

    total_expected = expected_q.scalar()
    total_collected = collected_q.scalar()
    total_due = total_expected - total_collected

    return render_template(
        "fees.html", rows=rows, total_expected=total_expected,
        total_collected=total_collected, total_due=total_due,
        pagination=pagination, q=q, class_filter=class_filter, class_choices=CLASS_CHOICES,
    )


@app.route("/fees/<int:student_id>", methods=["GET", "POST"])
@login_required
def student_fee_detail(student_id):
    s = Student.query.get_or_404(student_id)
    if not s.fee:
        s.fee = StudentFee(student_id=s.id, total_fee=0)
        db.session.add(s.fee)
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "update_total":
                total_fee = float(request.form.get("total_fee") or 0)
                if total_fee < 0:
                    flash("Total fee cannot be negative.")
                else:
                    s.fee.total_fee = total_fee
                    s.fee.due_date = request.form.get("due_date", "").strip()
                    db.session.commit()
                    flash("Fee structure updated.")
            elif action == "add_payment":
                amount = float(request.form.get("amount") or 0)
                if amount <= 0:
                    flash("Payment amount must be greater than zero.")
                else:
                    payment = FeePayment(
                        student_id=s.id, amount=amount,
                        date=request.form.get("date") or None,
                        mode=request.form.get("mode", "Cash"),
                        note=request.form.get("note", "").strip(),
                    )
                    db.session.add(payment)
                    db.session.commit()
                    flash(f"Payment of ₹{amount:,.2f} recorded.")
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            flash("Please enter a valid amount. Nothing was saved.")
        return redirect(url_for("student_fee_detail", student_id=s.id))

    paid = sum(p.amount for p in s.payments)
    balance = s.fee.total_fee - paid
    payments = sorted(s.payments, key=lambda p: p.id, reverse=True)
    return render_template("student_fee_detail.html", s=s, paid=paid, balance=balance, payments=payments)


@app.route("/fees/payment/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_payment(payment_id):
    p = FeePayment.query.get_or_404(payment_id)
    student_id = p.student_id
    db.session.delete(p)
    db.session.commit()
    flash("Payment entry removed.")
    return redirect(url_for("student_fee_detail", student_id=student_id))


@app.route("/fees/payment/<int:payment_id>/receipt")
@login_required
def fee_receipt(payment_id):
    p = FeePayment.query.get_or_404(payment_id)
    s = p.student
    return render_template(
        "receipt.html", kind="fee", payment=p, person=s,
        printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

@app.route("/teachers")
@login_required
def teachers():
    q = request.args.get("q", "").strip()
    page = get_page_arg()
    query = Teacher.query
    if q:
        query = query.filter(Teacher.name.ilike(f"%{q}%"))
    pagination = query.order_by(Teacher.name).paginate(page=page, per_page=PAGE_SIZE, error_out=False)
    return render_template("teachers.html", teachers=pagination.items, pagination=pagination, q=q)


@app.route("/teachers/add", methods=["GET", "POST"])
@login_required
def add_teacher():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Staff name is required.")
            return redirect(url_for("add_teacher"))
        try:
            monthly_salary = float(request.form.get("monthly_salary") or 0)
        except ValueError:
            flash("Monthly salary must be a number.")
            return redirect(url_for("add_teacher"))
        if monthly_salary < 0:
            flash("Monthly salary cannot be negative.")
            return redirect(url_for("add_teacher"))

        try:
            t = Teacher(
                name=name,
                subject=request.form.get("subject", "").strip(),
                contact=request.form.get("contact", "").strip(),
                joining_date=request.form.get("joining_date", "").strip(),
            )
            db.session.add(t)
            db.session.flush()
            salary = TeacherSalary(teacher_id=t.id, monthly_salary=monthly_salary)
            db.session.add(salary)
            db.session.commit()
            flash(f"Staff member {t.name} added successfully.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this staff member. Please try again.")
        return redirect(url_for("teachers"))
    return render_template("add_teacher.html")


@app.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    t = Teacher.query.get_or_404(teacher_id)
    db.session.delete(t)
    db.session.commit()
    flash("Staff record deleted.")
    return redirect(url_for("teachers"))

@app.route("/salary")
@login_required
def salary():
    q = request.args.get("q", "").strip()
    page = get_page_arg()

    paid_subq = (
        db.session.query(
            SalaryPayment.teacher_id.label("teacher_id"),
            func.sum(SalaryPayment.amount).label("paid"),
        )
        .group_by(SalaryPayment.teacher_id)
        .subquery()
    )

    query = (
        db.session.query(
            Teacher,
            func.coalesce(TeacherSalary.monthly_salary, 0).label("monthly"),
            func.coalesce(paid_subq.c.paid, 0).label("paid"),
        )
        .outerjoin(TeacherSalary, TeacherSalary.teacher_id == Teacher.id)
        .outerjoin(paid_subq, paid_subq.c.teacher_id == Teacher.id)
    )
    if q:
        query = query.filter(Teacher.name.ilike(f"%{q}%"))

    query = query.order_by(Teacher.name)
    pagination = query.paginate(page=page, per_page=PAGE_SIZE, error_out=False)

    rows = []
    for t, monthly, paid in pagination.items:
        balance = monthly - paid
        status = "Paid" if balance <= 0 and monthly > 0 else ("Not Set" if monthly == 0 else ("Partial" if paid > 0 else "Due"))
        rows.append({"teacher": t, "monthly": monthly, "paid": paid, "balance": balance, "status": status})

    total_expected = db.session.query(func.coalesce(func.sum(TeacherSalary.monthly_salary), 0)).scalar()
    total_paid = db.session.query(func.coalesce(func.sum(SalaryPayment.amount), 0)).scalar()
    total_due = total_expected - total_paid

    return render_template(
        "salary.html", rows=rows, total_expected=total_expected,
        total_paid=total_paid, total_due=total_due,
        pagination=pagination, q=q,
    )


@app.route("/salary/<int:teacher_id>", methods=["GET", "POST"])
@login_required
def teacher_salary_detail(teacher_id):
    t = Teacher.query.get_or_404(teacher_id)
    if not t.salary:
        t.salary = TeacherSalary(teacher_id=t.id, monthly_salary=0)
        db.session.add(t.salary)
        db.session.commit()

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "update_salary":
                monthly_salary = float(request.form.get("monthly_salary") or 0)
                if monthly_salary < 0:
                    flash("Monthly salary cannot be negative.")
                else:
                    t.salary.monthly_salary = monthly_salary
                    db.session.commit()
                    flash("Salary structure updated.")
            elif action == "add_payment":
                amount = float(request.form.get("amount") or 0)
                if amount <= 0:
                    flash("Payment amount must be greater than zero.")
                else:
                    payment = SalaryPayment(
                        teacher_id=t.id, amount=amount,
                        date=request.form.get("date") or None,
                        note=request.form.get("note", "").strip(),
                    )
                    db.session.add(payment)
                    db.session.commit()
                    flash(f"Salary payment of ₹{amount:,.2f} recorded.")
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            flash("Please enter a valid amount. Nothing was saved.")
        return redirect(url_for("teacher_salary_detail", teacher_id=t.id))

    paid = sum(p.amount for p in t.salary_payments)
    balance = t.salary.monthly_salary - paid
    payments = sorted(t.salary_payments, key=lambda p: p.id, reverse=True)
    return render_template("teacher_salary_detail.html", t=t, paid=paid, balance=balance, payments=payments)


@app.route("/salary/payment/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_salary_payment(payment_id):
    p = SalaryPayment.query.get_or_404(payment_id)
    teacher_id = p.teacher_id
    db.session.delete(p)
    db.session.commit()
    flash("Payment entry removed.")
    return redirect(url_for("teacher_salary_detail", teacher_id=teacher_id))


@app.route("/salary/payment/<int:payment_id>/receipt")
@login_required
def salary_receipt(payment_id):
    p = SalaryPayment.query.get_or_404(payment_id)
    t = p.teacher
    return render_template(
        "receipt.html", kind="salary", payment=p, person=t,
        printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/expenses")
@login_required
def expenses():
    q = request.args.get("q", "").strip()
    category_filter = request.args.get("category", "").strip()
    page = get_page_arg()

    query = Expense.query
    if category_filter and category_filter in EXPENSE_CATEGORIES:
        query = query.filter(Expense.category == category_filter)
    if q:
        query = query.filter(Expense.title.ilike(f"%{q}%"))

    total_matching = query.count()
    pagination = query.order_by(Expense.id.desc()).paginate(page=page, per_page=PAGE_SIZE, error_out=False)

    total_q = db.session.query(func.coalesce(func.sum(Expense.amount), 0))
    if category_filter and category_filter in EXPENSE_CATEGORIES:
        total_q = total_q.filter(Expense.category == category_filter)
    if q:
        total_q = total_q.filter(Expense.title.ilike(f"%{q}%"))
    total_expenses = total_q.scalar()

    return render_template(
        "expenses.html",
        expenses=pagination.items,
        pagination=pagination,
        total_matching=total_matching,
        total_expenses=total_expenses,
        q=q,
        category_filter=category_filter,
        category_choices=EXPENSE_CATEGORIES,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title or not category:
            flash("Title and category are required.")
            return redirect(url_for("add_expense"))

        if category not in EXPENSE_CATEGORIES:
            flash("Please choose a category from the list.")
            return redirect(url_for("add_expense"))

        try:
            amount = float(request.form.get("amount") or 0)
        except ValueError:
            flash("Amount must be a number.")
            return redirect(url_for("add_expense"))
        if amount <= 0:
            flash("Amount must be greater than zero.")
            return redirect(url_for("add_expense"))

        try:
            e = Expense(
                title=title,
                category=category,
                amount=amount,
                date=request.form.get("date") or datetime.now().strftime("%Y-%m-%d"),
                note=request.form.get("note", "").strip(),
            )
            db.session.add(e)
            db.session.commit()
            flash(f"Expense of ₹{amount:,.2f} for '{title}' recorded.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this expense. Please try again.")
        return redirect(url_for("expenses"))

    return render_template("add_expense.html", category_choices=EXPENSE_CATEGORIES)


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    e = Expense.query.get_or_404(expense_id)
    db.session.delete(e)
    db.session.commit()
    flash("Expense entry removed.")
    return redirect(url_for("expenses"))


with app.app_context():
    db.create_all()
    seed_admin()

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="127.0.0.1", port=5000)
