from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Expense
from constants import EXPENSE_CATEGORIES
from helpers import login_required, paginate

bp = Blueprint("expenses", __name__)


@bp.route("/expenses")
@login_required
def expenses():
    q = request.args.get("q", "").strip()
    category_filter = request.args.get("category", "").strip()

    query = Expense.query
    if category_filter and category_filter in EXPENSE_CATEGORIES:
        query = query.filter(Expense.category == category_filter)
    if q:
        query = query.filter(Expense.title.ilike(f"%{q}%"))

    total_matching = query.count()
    pagination = paginate(query.order_by(Expense.id.desc()))

    total_q = db.session.query(func.coalesce(func.sum(Expense.amount), 0))
    if category_filter and category_filter in EXPENSE_CATEGORIES:
        total_q = total_q.filter(Expense.category == category_filter)
    if q:
        total_q = total_q.filter(Expense.title.ilike(f"%{q}%"))
    total_expenses = total_q.scalar()

    return render_template(
        "expenses.html", expenses=pagination.items, pagination=pagination, total_matching=total_matching,
        total_expenses=total_expenses, q=q, category_filter=category_filter, category_choices=EXPENSE_CATEGORIES,
    )


@bp.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title or not category:
            flash("Title and category are required.")
            return redirect(url_for("expenses.add_expense"))
        if category not in EXPENSE_CATEGORIES:
            flash("Please choose a category from the list.")
            return redirect(url_for("expenses.add_expense"))
        if category == "Other":
            custom_category = request.form.get("custom_category", "").strip()
            if custom_category:
                category = custom_category

        try:
            amount = float(request.form.get("amount") or 0)
        except ValueError:
            flash("Amount must be a number.")
            return redirect(url_for("expenses.add_expense"))
        if amount <= 0:
            flash("Amount must be greater than zero.")
            return redirect(url_for("expenses.add_expense"))

        try:
            db.session.add(Expense(
                title=title, category=category, amount=amount,
                date=request.form.get("date") or datetime.now().strftime("%Y-%m-%d"),
                note=request.form.get("note", "").strip(),
            ))
            db.session.commit()
            flash(f"Expense of ₹{amount:,.2f} for '{title}' recorded.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save this expense. Please try again.")
        return redirect(url_for("expenses.expenses"))

    return render_template("add_expense.html", category_choices=EXPENSE_CATEGORIES)


@bp.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    e = Expense.query.get_or_404(expense_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        if not title or not category:
            flash("Title and category are required.")
            return redirect(url_for("expenses.edit_expense", expense_id=e.id))
        if category not in EXPENSE_CATEGORIES:
            flash("Please choose a category from the list.")
            return redirect(url_for("expenses.edit_expense", expense_id=e.id))
        if category == "Other":
            custom_category = request.form.get("custom_category", "").strip()
            if custom_category:
                category = custom_category

        try:
            amount = float(request.form.get("amount") or 0)
        except ValueError:
            flash("Amount must be a number.")
            return redirect(url_for("expenses.edit_expense", expense_id=e.id))
        if amount <= 0:
            flash("Amount must be greater than zero.")
            return redirect(url_for("expenses.edit_expense", expense_id=e.id))

        try:
            e.title = title
            e.category = category
            e.amount = amount
            e.date = request.form.get("date") or e.date
            e.note = request.form.get("note", "").strip()
            db.session.commit()
            flash(f"Expense entry for '{e.title}' updated.")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Could not save these changes. Please try again.")
        return redirect(url_for("expenses.expenses"))

    return render_template("edit_expense.html", e=e, category_choices=EXPENSE_CATEGORIES)


@bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    e = Expense.query.get_or_404(expense_id)
    db.session.delete(e)
    db.session.commit()
    flash("Expense entry removed.")
    return redirect(url_for("expenses.expenses"))
