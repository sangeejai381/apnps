from flask import Blueprint, render_template
from sqlalchemy import func

from extensions import db
from models import Expense, FeePayment, SalaryPayment, Student, StudentFee, Teacher, TeacherSalary
from helpers import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
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
