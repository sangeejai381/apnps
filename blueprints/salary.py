from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import SalaryPayment, Teacher, TeacherSalary
from helpers import login_required, paginate

bp = Blueprint("salary", __name__)


@bp.route("/salary")
@login_required
def salary():
    q = request.args.get("q", "").strip()

    paid_subq = (
        db.session.query(SalaryPayment.teacher_id.label("teacher_id"), func.sum(SalaryPayment.amount).label("paid"))
        .group_by(SalaryPayment.teacher_id).subquery()
    )
    query = (
        db.session.query(Teacher, func.coalesce(TeacherSalary.monthly_salary, 0).label("monthly"), func.coalesce(paid_subq.c.paid, 0).label("paid"))
        .outerjoin(TeacherSalary, TeacherSalary.teacher_id == Teacher.id)
        .outerjoin(paid_subq, paid_subq.c.teacher_id == Teacher.id)
    )
    if q:
        query = query.filter(Teacher.name.ilike(f"%{q}%"))
    pagination = paginate(query.order_by(Teacher.name))

    rows = []
    for t, monthly, paid in pagination.items:
        balance = monthly - paid
        status = "Paid" if balance <= 0 and monthly > 0 else ("Not Set" if monthly == 0 else ("Partial" if paid > 0 else "Due"))
        rows.append({"teacher": t, "monthly": monthly, "paid": paid, "balance": balance, "status": status})

    total_expected = db.session.query(func.coalesce(func.sum(TeacherSalary.monthly_salary), 0)).scalar()
    total_paid = db.session.query(func.coalesce(func.sum(SalaryPayment.amount), 0)).scalar()
    total_due = total_expected - total_paid

    return render_template(
        "salary.html", rows=rows, total_expected=total_expected, total_paid=total_paid, total_due=total_due,
        pagination=pagination, q=q,
    )


@bp.route("/salary/<int:teacher_id>", methods=["GET", "POST"])
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
                        teacher_id=t.id, amount=amount, date=request.form.get("date") or None,
                        note=request.form.get("note", "").strip(),
                    )
                    db.session.add(payment)
                    db.session.commit()
                    flash(f"Salary payment of ₹{amount:,.2f} recorded.")
            elif action == "edit_payment":
                payment = SalaryPayment.query.get_or_404(int(request.form.get("payment_id")))
                if payment.teacher_id != t.id:
                    flash("That payment doesn't belong to this staff member.")
                else:
                    amount = float(request.form.get("amount") or 0)
                    if amount <= 0:
                        flash("Payment amount must be greater than zero.")
                    else:
                        payment.amount = amount
                        payment.date = request.form.get("date") or payment.date
                        payment.note = request.form.get("note", "").strip()
                        db.session.commit()
                        flash("Payment entry updated.")
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            flash("Please enter a valid amount. Nothing was saved.")
        return redirect(url_for("salary.teacher_salary_detail", teacher_id=t.id))

    paid = sum(p.amount for p in t.salary_payments)
    balance = t.salary.monthly_salary - paid
    payments = sorted(t.salary_payments, key=lambda p: p.id, reverse=True)
    return render_template("teacher_salary_detail.html", t=t, paid=paid, balance=balance, payments=payments)


@bp.route("/salary/payment/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_salary_payment(payment_id):
    p = SalaryPayment.query.get_or_404(payment_id)
    teacher_id = p.teacher_id
    db.session.delete(p)
    db.session.commit()
    flash("Payment entry removed.")
    return redirect(url_for("salary.teacher_salary_detail", teacher_id=teacher_id))


@bp.route("/salary/payment/<int:payment_id>/receipt")
@login_required
def salary_receipt(payment_id):
    p = SalaryPayment.query.get_or_404(payment_id)
    t = p.teacher
    return render_template("receipt.html", kind="salary", payment=p, person=t, printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"))
