from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Teacher, TeacherSalary
from helpers import login_required, paginate

bp = Blueprint("teachers", __name__)


@bp.route("/teachers")
@login_required
def teachers():
    q = request.args.get("q", "").strip()
    query = Teacher.query
    if q:
        query = query.filter(Teacher.name.ilike(f"%{q}%"))
    pagination = paginate(query.order_by(Teacher.name))
    return render_template("teachers.html", teachers=pagination.items, pagination=pagination, q=q)


@bp.route("/teachers/add", methods=["GET", "POST"])
@login_required
def add_teacher():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Staff name is required.")
            return redirect(url_for("teachers.add_teacher"))
        try:
            monthly_salary = float(request.form.get("monthly_salary") or 0)
        except ValueError:
            flash("Monthly salary must be a number.")
            return redirect(url_for("teachers.add_teacher"))
        if monthly_salary < 0:
            flash("Monthly salary cannot be negative.")
            return redirect(url_for("teachers.add_teacher"))

        try:
            t = Teacher(
                name=name, subject=request.form.get("subject", "").strip(),
                contact=request.form.get("contact", "").strip(),
                joining_date=request.form.get("joining_date", "").strip(),
            )
            db.session.add(t)
            db.session.flush()
            db.session.add(TeacherSalary(teacher_id=t.id, monthly_salary=monthly_salary))
            db.session.commit()
            flash(f"Staff member {t.name} added successfully.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this staff member. Please try again.")
        return redirect(url_for("teachers.teachers"))
    return render_template("add_teacher.html")


@bp.route("/teachers/<int:teacher_id>/edit", methods=["GET", "POST"])
@login_required
def edit_teacher(teacher_id):
    t = Teacher.query.get_or_404(teacher_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Staff name is required.")
            return redirect(url_for("teachers.edit_teacher", teacher_id=t.id))
        try:
            t.name = name
            t.subject = request.form.get("subject", "").strip()
            t.contact = request.form.get("contact", "").strip()
            t.joining_date = request.form.get("joining_date", "").strip()
            db.session.commit()
            flash(f"Staff record for {t.name} updated.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save these changes. Please try again.")
        return redirect(url_for("teachers.teachers"))
    return render_template("edit_teacher.html", t=t)


@bp.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    t = Teacher.query.get_or_404(teacher_id)
    db.session.delete(t)
    db.session.commit()
    flash("Staff record deleted.")
    return redirect(url_for("teachers.teachers"))
