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
    roll_no = db.Column(db.String(40), nullable=False)
    parent_name = db.Column(db.String(120))
    contact = db.Column(db.String(20))
    admission_date = db.Column(db.String(20))

    __table_args__ = (db.UniqueConstraint("class_name", "roll_no", name="uq_class_roll"),)

    fee = db.relationship("StudentFee", backref="student", uselist=False, cascade="all, delete-orphan")
    payments = db.relationship("FeePayment", backref="student", cascade="all, delete-orphan")


class StudentFee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    total_fee = db.Column(db.Float, nullable=False, default=0)
    due_date = db.Column(db.String(20))


class FeePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default=lambda: datetime.now().strftime("%Y-%m-%d"))
    mode = db.Column(db.String(20), default="Cash")
    note = db.Column(db.String(200))


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
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), default=lambda: datetime.now().strftime("%Y-%m-%d"))
    note = db.Column(db.String(200))
