from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import FeeStructure
from constants import CLASS_CHOICES, FEE_CATEGORIES
from helpers import current_academic_year, login_required, previous_academic_year

bp = Blueprint("fee_structure", __name__)


@bp.route("/fee-structure")
@login_required
def fee_structure():
    class_name = request.args.get("class_name", "").strip() or CLASS_CHOICES[0]
    academic_year = request.args.get("academic_year", "").strip() or current_academic_year()
    if class_name not in CLASS_CHOICES:
        class_name = CLASS_CHOICES[0]

    rows = FeeStructure.query.filter_by(class_name=class_name, academic_year=academic_year).order_by(FeeStructure.id).all()
    total = sum(row.amount for row in rows)
    prev_year = previous_academic_year(academic_year)
    prev_year_has_rows = bool(
        prev_year and FeeStructure.query.filter_by(class_name=class_name, academic_year=prev_year).first()
    )

    return render_template(
        "fee_structure.html", class_name=class_name, academic_year=academic_year,
        rows=rows, total=total, class_choices=CLASS_CHOICES, category_choices=FEE_CATEGORIES,
        prev_year=prev_year, prev_year_has_rows=prev_year_has_rows,
    )


@bp.route("/fee-structure/add", methods=["POST"])
@login_required
def add_fee_structure_row():
    class_name = request.form.get("class_name", "").strip()
    academic_year = request.form.get("academic_year", "").strip()
    category = request.form.get("category", "").strip()
    custom_category = ""

    if class_name not in CLASS_CHOICES:
        flash("Please choose a class from the list.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))
    if not academic_year:
        flash("Academic year is required.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))
    if category not in FEE_CATEGORIES:
        flash("Please choose a category from the list.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))
    if category == "Other":
        custom_category = request.form.get("custom_category", "").strip()
        if not custom_category:
            flash('Please specify a name for the "Other" category.')
            return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))

    try:
        amount = float(request.form.get("amount") or 0)
    except ValueError:
        flash("Amount must be a number.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))
    if amount <= 0:
        flash("Amount must be greater than zero.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))

    dup = FeeStructure.query.filter_by(
        class_name=class_name, academic_year=academic_year, category=category, custom_category=custom_category,
    ).first()
    if dup:
        flash("That category already exists for this class/year — edit it below instead of adding it again.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))

    try:
        db.session.add(FeeStructure(
            class_name=class_name, academic_year=academic_year,
            category=category, custom_category=custom_category, amount=amount,
        ))
        db.session.commit()
        flash("Category added to the fee structure.")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Could not save this category. Please try again.")
    return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))


@bp.route("/fee-structure/<int:row_id>/edit", methods=["POST"])
@login_required
def edit_fee_structure_row(row_id):
    row = FeeStructure.query.get_or_404(row_id)
    try:
        amount = float(request.form.get("amount") or 0)
        if amount <= 0:
            flash("Amount must be greater than zero.")
        else:
            row.amount = amount
            db.session.commit()
            flash("Category amount updated. Existing students already using this category keep their own amount — use \"Reset to class structure\" on a student's fee page to apply this new default to them.")
    except (ValueError, SQLAlchemyError):
        db.session.rollback()
        flash("Please enter a valid amount. Nothing was saved.")
    return redirect(url_for("fee_structure.fee_structure", class_name=row.class_name, academic_year=row.academic_year))


@bp.route("/fee-structure/<int:row_id>/delete", methods=["POST"])
@login_required
def delete_fee_structure_row(row_id):
    row = FeeStructure.query.get_or_404(row_id)
    class_name, academic_year = row.class_name, row.academic_year
    db.session.delete(row)
    db.session.commit()
    flash("Category removed from the fee structure. Students who already had this category keep it until manually reset.")
    return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))


@bp.route("/fee-structure/copy-previous-year", methods=["POST"])
@login_required
def copy_fee_structure_previous_year():
    class_name = request.form.get("class_name", "").strip()
    academic_year = request.form.get("academic_year", "").strip()
    prev_year = previous_academic_year(academic_year)

    if not prev_year:
        flash("Couldn't determine the previous academic year.")
        return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))

    prev_rows = FeeStructure.query.filter_by(class_name=class_name, academic_year=prev_year).order_by(FeeStructure.id).all()
    copied, skipped = 0, 0
    for row in prev_rows:
        exists = FeeStructure.query.filter_by(
            class_name=class_name, academic_year=academic_year,
            category=row.category, custom_category=row.custom_category,
        ).first()
        if exists:
            skipped += 1
            continue
        db.session.add(FeeStructure(
            class_name=class_name, academic_year=academic_year,
            category=row.category, custom_category=row.custom_category, amount=row.amount,
        ))
        copied += 1
    db.session.commit()

    if copied:
        msg = f"Copied {copied} categor{'y' if copied == 1 else 'ies'} from {prev_year}."
        if skipped:
            msg += f" {skipped} already existed in {academic_year} and were left as-is."
        flash(msg)
    elif skipped:
        flash(f"All of {prev_year}'s categories already exist in {academic_year} — nothing new to copy.")
    else:
        flash(f"No fee structure found for {class_name} in {prev_year} to copy from.")
    return redirect(url_for("fee_structure.fee_structure", class_name=class_name, academic_year=academic_year))


@bp.route("/fee-structure/print")
@login_required
def print_fee_structure():
    class_name = request.args.get("class_name", "").strip()
    academic_year = request.args.get("academic_year", "").strip()
    rows = FeeStructure.query.filter_by(class_name=class_name, academic_year=academic_year).order_by(FeeStructure.id).all()
    total = sum(row.amount for row in rows)
    return render_template(
        "fee_structure_sheet.html", class_name=class_name, academic_year=academic_year,
        rows=rows, total=total, printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@bp.route("/fee-structure/print-all")
@login_required
def print_fee_structure_all():
    academic_year = request.args.get("academic_year", "").strip() or current_academic_year()
    classes = []
    for class_name in CLASS_CHOICES:
        rows = FeeStructure.query.filter_by(class_name=class_name, academic_year=academic_year).order_by(FeeStructure.id).all()
        if rows:
            classes.append({"class_name": class_name, "rows": rows, "total": sum(row.amount for row in rows)})
    return render_template(
        "fee_structure_all_classes.html", academic_year=academic_year, classes=classes,
        printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
