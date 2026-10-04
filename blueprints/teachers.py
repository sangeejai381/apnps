from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Teacher, TeacherSalary
from constants import CLASS_CHOICES, SECTION_CHOICES
from helpers import login_required, paginate, set_teacher_password

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

        portal_email = request.form.get("portal_email", "").strip().lower()
        new_password = request.form.get("portal_password", "").strip()
        portal_active = request.form.get("portal_active") == "on"

        if portal_email:
            email_taken = (
                Teacher.query.filter(Teacher.id != t.id, func.lower(Teacher.email) == portal_email).first()
            )
            if email_taken:
                flash(f"That email is already used for another teacher's portal login ({email_taken.name}).")
                return redirect(url_for("teachers.edit_teacher", teacher_id=t.id))

        if portal_active and not portal_email:
            flash("Portal access needs a login email — enter one, or leave portal access off.")
            return redirect(url_for("teachers.edit_teacher", teacher_id=t.id))
        if portal_active and not new_password and not t.password_hash:
            flash("This teacher doesn't have a password set yet — set one before turning portal access on.")
            return redirect(url_for("teachers.edit_teacher", teacher_id=t.id))
        if new_password and len(new_password) < 6:
            flash("Portal password must be at least 6 characters.")
            return redirect(url_for("teachers.edit_teacher", teacher_id=t.id))

        try:
            t.name = name
            t.subject = request.form.get("subject", "").strip()
            t.contact = request.form.get("contact", "").strip()
            t.joining_date = request.form.get("joining_date", "").strip()

            t.email = portal_email or None
            t.assigned_class = request.form.get("assigned_class", "").strip() or None
            t.assigned_section = request.form.get("assigned_section", "").strip() or None
            t.portal_active = portal_active
            if new_password:
                set_teacher_password(t, new_password)

            db.session.commit()
            flash(f"Staff record for {t.name} updated.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save these changes. Please try again.")
        return redirect(url_for("teachers.teachers"))
    return render_template("edit_teacher.html", t=t, class_choices=CLASS_CHOICES, section_choices=SECTION_CHOICES)


@bp.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@login_required
def delete_teacher(teacher_id):
    t = Teacher.query.get_or_404(teacher_id)
    db.session.delete(t)
    db.session.commit()
    flash("Staff record deleted.")
    return redirect(url_for("teachers.teachers"))
