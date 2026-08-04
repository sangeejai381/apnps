from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    pin = db.Column(db.String(10), nullable=False)
    name = db.Column(db.String(120), nullable=False)


class LoginAttempt(db.Model):
    """
    Tracks failed login attempts per identifier (email/mobile typed on the
    login form). Backed by the database (not an in-memory dict) so lockouts
    survive app restarts and work correctly even if the app is later run
    with multiple worker processes.
    """
    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), unique=True, nullable=False, index=True)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    class_name = db.Column(db.String(40), nullable=False, index=True)
    section = db.Column(db.String(10), index=True)
    roll_no = db.Column(db.String(40), nullable=False)
    dob = db.Column(db.String(20))
    parent_name = db.Column(db.String(120))
    contact = db.Column(db.String(20))
    address = db.Column(db.String(250))
    admission_date = db.Column(db.String(20))

    __table_args__ = (db.UniqueConstraint("class_name", "roll_no", name="uq_class_roll"),)

    fee = db.relationship("StudentFee", backref="student", uselist=False, cascade="all, delete-orphan")
    payments = db.relationship("FeePayment", backref="student", cascade="all, delete-orphan")
    fee_items = db.relationship("StudentFeeItem", backref="student", cascade="all, delete-orphan")


class StudentFee(db.Model):
    """
    Cached rollup of a student's fee total for one academic year — kept so
    every place that already reads StudentFee.total_fee (dashboard totals,
    Fee Management list, class-wise breakdowns) keeps working unchanged.
    The real, itemized detail lives in StudentFeeItem; total_fee here is
    just SUM(StudentFeeItem.amount) for (student_id, academic_year),
    recalculated by app.py whenever items are added, edited, removed, or
    reset — never edited directly by hand once items exist for a year.
    """
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    total_fee = db.Column(db.Float, nullable=False, default=0)
    due_date = db.Column(db.String(20))
    academic_year = db.Column(db.String(20))


class FeeStructure(db.Model):
    """
    The class-level fee template: what each category *should* cost for a
    given class, in a given academic year. This is the "menu" — actual
    per-student charges live in StudentFeeItem, generated from this but
    independently editable (so one student's scholarship/discount doesn't
    require touching the whole class's structure).
    custom_category is stored as "" (never NULL) when not applicable, so
    the uniqueness check below works reliably at the database level too —
    NULL != NULL in SQL, which would otherwise silently let two "Tuition
    Fee" rows exist for the same class/year.
    """
    id = db.Column(db.Integer, primary_key=True)
    class_name = db.Column(db.String(40), nullable=False, index=True)
    academic_year = db.Column(db.String(20), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)
    custom_category = db.Column(db.String(80), nullable=False, default="")
    amount = db.Column(db.Float, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "class_name", "academic_year", "category", "custom_category",
            name="uq_feestructure_class_year_category",
        ),
    )


class StudentFeeItem(db.Model):
    """
    One line item of a specific student's fee for one academic year (e.g.
    "Tuition Fee: ₹12,000" or "Other — Annual Day Fund: ₹500"). Normally
    created by copying a class's FeeStructure when the student is added or
    when "Reset to class structure" is used, but each item can then be
    edited independently — a discount on one student's Book Fee doesn't
    touch the class-wide structure or any other student.
    note is required (validated in app.py, not just hinted in the UI)
    whenever an item's amount is edited away from what the matching
    FeeStructure entry defines, so a discount is always explained rather
    than silently different from the standard rate.
    """
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    academic_year = db.Column(db.String(20), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)
    custom_category = db.Column(db.String(80), nullable=False, default="")
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(300))

    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "academic_year", "category", "custom_category",
            name="uq_studentfeeitem_student_year_category",
        ),
    )


class FeePayment(db.Model):
    """
    fee_item_id ties a payment to one specific StudentFeeItem (e.g. "this
    ₹500 was for Book Fee") so paid/balance can be tracked per category, not
    just as one lump sum. NULL means a general/unallocated payment not
    assigned to any particular category — the default for payments made
    before this feature existed, and still available as an option so an
    admin can record a payment without splitting it by category.
    """
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    fee_item_id = db.Column(db.Integer, db.ForeignKey("student_fee_item.id"), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default=lambda: datetime.now().strftime("%Y-%m-%d"))
    mode = db.Column(db.String(20), default="Cash")
    note = db.Column(db.String(200))

    fee_item = db.relationship("StudentFeeItem", backref="payments")


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    subject = db.Column(db.String(80))
    contact = db.Column(db.String(20))
    joining_date = db.Column(db.String(20))

    salary = db.relationship("TeacherSalary", backref="teacher", uselist=False, cascade="all, delete-orphan")
    salary_payments = db.relationship("SalaryPayment", backref="teacher", cascade="all, delete-orphan")


class TeacherSalary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    monthly_salary = db.Column(db.Float, nullable=False, default=0)


class SalaryPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default=lambda: datetime.now().strftime("%Y-%m-%d"))
    note = db.Column(db.String(200))


class Expense(db.Model):
    """
    General school expenses — books, furniture, equipment, repairs, events,
    etc. Separate from student fees and staff salary; this tracks money
    going out for running/upgrading the school itself.
    """
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default=lambda: datetime.now().strftime("%Y-%m-%d"))
    note = db.Column(db.String(200))


class Message(db.Model):
    """
    Shared internal notice board / chat. The whole school uses one shared
    login (there's no separate per-teacher account), so instead of tagging
    every post to a fixed "Admin" identity, each post carries whatever name
    the poster typed in at the time they sent it. This lets the admin post
    something ("no school Friday", "submit attendance by 5pm") and any
    teacher using the portal — on the same shared login — sees it and can
    reply in the same thread, all without needing individual logins.
    """
    id = db.Column(db.Integer, primary_key=True)
    posted_by = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    posted_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
