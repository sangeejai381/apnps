from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import FeePayment, FeeStructure, Student, StudentFee, StudentFeeItem
from constants import CLASS_CHOICES, CONCESSION_CATEGORY, CONCESSION_REASONS, FEE_CATEGORIES
from helpers import current_academic_year, get_page_arg, login_required, paginate, recompute_student_fee_total

bp = Blueprint("fees", __name__)


def _refresh_current_year_cache(student):
    """
    StudentFee.total_fee/academic_year is a single cached "what this student
    owes right now" figure — read everywhere else (Fee Ledger, dashboard
    totals, class-wise breakdowns). It must always reflect the school's
    actual current academic year, regardless of which year's fee items an
    admin happens to be editing on this page (e.g. entering historical
    2024-25 dues shouldn't make the ledger suddenly show 2024-25's total
    instead of 2026-27's). So every mutation recomputes the cache against
    current_academic_year() specifically, never against the edited year.
    """
    recompute_student_fee_total(student, current_academic_year())


@bp.route("/fees")
@login_required
def fees():
    q = request.args.get("q", "").strip()
    class_filter = request.args.get("class_name", "").strip()

    paid_subq = (
        db.session.query(FeePayment.student_id.label("student_id"), func.sum(FeePayment.amount).label("paid"))
        .group_by(FeePayment.student_id).subquery()
    )
    # Per-student total concession/discount for whichever academic year their
    # cached StudentFee total currently reflects — matches the fact that
    # StudentFee.total_fee/academic_year is itself a single "current" rollup
    # per student (see recompute_student_fee_total), not split by year here.
    concession_subq = (
        db.session.query(
            StudentFeeItem.student_id.label("student_id"),
            StudentFeeItem.academic_year.label("academic_year"),
            func.sum(StudentFeeItem.amount).label("concession_total"),
        )
        .filter(StudentFeeItem.category == CONCESSION_CATEGORY)
        .group_by(StudentFeeItem.student_id, StudentFeeItem.academic_year)
        .subquery()
    )
    query = (
        db.session.query(
            Student,
            func.coalesce(StudentFee.total_fee, 0).label("total"),
            func.coalesce(paid_subq.c.paid, 0).label("paid"),
            func.coalesce(concession_subq.c.concession_total, 0).label("concession"),
        )
        .outerjoin(StudentFee, StudentFee.student_id == Student.id)
        .outerjoin(paid_subq, paid_subq.c.student_id == Student.id)
        .outerjoin(
            concession_subq,
            db.and_(
                concession_subq.c.student_id == Student.id,
                concession_subq.c.academic_year == StudentFee.academic_year,
            ),
        )
    )
    if class_filter and class_filter in CLASS_CHOICES:
        query = query.filter(Student.class_name == class_filter)
    if q:
        query = query.filter(db.or_(Student.name.ilike(f"%{q}%"), Student.roll_no.ilike(f"%{q}%")))

    query = query.order_by(Student.class_name, Student.name)
    pagination = paginate(query)

    rows = []
    for s, total, paid, concession in pagination.items:
        balance = total - paid
        status = "Paid" if balance <= 0 and total > 0 else ("Not Set" if total == 0 else ("Partial" if paid > 0 else "Due"))
        concession_amount = abs(concession)
        rows.append({
            "student": s, "gross_total": total + concession_amount, "total": total, "paid": paid,
            "balance": balance, "status": status, "concession": concession_amount,
        })

    expected_q = db.session.query(func.coalesce(func.sum(StudentFee.total_fee), 0)).join(Student, Student.id == StudentFee.student_id)
    collected_q = db.session.query(func.coalesce(func.sum(FeePayment.amount), 0)).join(Student, Student.id == FeePayment.student_id)
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
        "fees.html", rows=rows, total_expected=total_expected, total_collected=total_collected, total_due=total_due,
        pagination=pagination, q=q, class_filter=class_filter, class_choices=CLASS_CHOICES,
    )


@bp.route("/fees/<int:student_id>", methods=["GET", "POST"])
@login_required
def student_fee_detail(student_id):
    s = Student.query.get_or_404(student_id)
    if not s.fee:
        s.fee = StudentFee(student_id=s.id, total_fee=0)
        db.session.add(s.fee)
        db.session.commit()

    viewing_year = request.args.get("year", "").strip() or s.fee.academic_year or current_academic_year()

    if request.method == "POST":
        action = request.form.get("action")
        action_year = request.form.get("academic_year", "").strip() or viewing_year
        try:
            if action == "add_item":
                category = request.form.get("category", "").strip()
                custom_category = ""
                if category not in FEE_CATEGORIES:
                    flash("Please choose a category from the list.")
                elif category == "Other" and not request.form.get("custom_category", "").strip():
                    flash('Please specify a name for the "Other" category.')
                else:
                    if category == "Other":
                        custom_category = request.form.get("custom_category", "").strip()
                    amount = float(request.form.get("amount") or 0)
                    if amount <= 0:
                        flash("Amount must be greater than zero.")
                    else:
                        dup = StudentFeeItem.query.filter_by(
                            student_id=s.id, academic_year=action_year, category=category, custom_category=custom_category,
                        ).first()
                        if dup:
                            flash("This category already exists for this year — edit it below instead of adding it again.")
                        else:
                            db.session.add(StudentFeeItem(
                                student_id=s.id, academic_year=action_year, category=category,
                                custom_category=custom_category, amount=amount,
                                note=request.form.get("note", "").strip() or None,
                            ))
                            _refresh_current_year_cache(s)
                            db.session.commit()
                            flash("Fee item added.")

            elif action == "add_concession":
                reason = request.form.get("reason", "").strip()
                if reason not in CONCESSION_REASONS:
                    flash("Please choose a concession/discount reason from the list.")
                else:
                    amount = float(request.form.get("amount") or 0)
                    if amount <= 0:
                        flash("Discount amount must be greater than zero.")
                    else:
                        dup = StudentFeeItem.query.filter_by(
                            student_id=s.id, academic_year=action_year,
                            category=CONCESSION_CATEGORY, custom_category=reason,
                        ).first()
                        if dup:
                            flash("A concession with this reason already exists for this year — edit or remove it below instead.")
                        else:
                            db.session.add(StudentFeeItem(
                                student_id=s.id, academic_year=action_year, category=CONCESSION_CATEGORY,
                                custom_category=reason, amount=-abs(amount),
                                note=request.form.get("note", "").strip() or None,
                            ))
                            _refresh_current_year_cache(s)
                            db.session.commit()
                            flash(f"Concession of ₹{amount:,.2f} ({reason}) applied — total fee reduced.")

            elif action == "edit_item":
                item = StudentFeeItem.query.get_or_404(int(request.form.get("item_id")))
                if item.student_id != s.id:
                    flash("That fee item doesn't belong to this student.")
                else:
                    amount = float(request.form.get("amount") or 0)
                    note = request.form.get("note", "").strip()
                    is_concession = item.category == CONCESSION_CATEGORY
                    if is_concession:
                        if amount == 0:
                            flash("Discount amount cannot be zero.")
                        else:
                            # Whatever sign the admin types, a concession always
                            # reduces the total — normalize to negative.
                            item.amount = -abs(amount)
                            item.note = note or None
                            _refresh_current_year_cache(s)
                            db.session.commit()
                            flash("Concession updated.")
                    elif amount <= 0:
                        flash("Amount must be greater than zero.")
                    else:
                        structure_row = FeeStructure.query.filter_by(
                            class_name=s.class_name, academic_year=item.academic_year,
                            category=item.category, custom_category=item.custom_category,
                        ).first()
                        differs_from_structure = structure_row is not None and amount != structure_row.amount
                        if differs_from_structure and not note:
                            flash(
                                f"This differs from the standard ₹{structure_row.amount:,.2f} for "
                                f"{item.custom_category or item.category} — please add a note explaining why."
                            )
                        else:
                            item.amount = amount
                            item.note = note or None
                            _refresh_current_year_cache(s)
                            db.session.commit()
                            flash("Fee item updated.")

            elif action == "delete_item":
                item = StudentFeeItem.query.get_or_404(int(request.form.get("item_id")))
                if item.student_id == s.id:
                    item_year = item.academic_year
                    # Payments already recorded against this item shouldn't
                    # vanish — they become general/unallocated instead.
                    FeePayment.query.filter_by(fee_item_id=item.id).update({"fee_item_id": None})
                    db.session.delete(item)
                    _refresh_current_year_cache(s)
                    db.session.commit()
                    flash("Fee item removed. Any payments recorded against it are now unallocated.")

            elif action == "reset_to_structure":
                old_item_ids = [
                    row.id for row in StudentFeeItem.query.filter_by(student_id=s.id, academic_year=action_year).all()
                ]
                if old_item_ids:
                    FeePayment.query.filter(FeePayment.fee_item_id.in_(old_item_ids)).update(
                        {"fee_item_id": None}, synchronize_session=False
                    )
                StudentFeeItem.query.filter_by(student_id=s.id, academic_year=action_year).delete()
                structure_rows = FeeStructure.query.filter_by(class_name=s.class_name, academic_year=action_year).order_by(FeeStructure.id).all()
                for row in structure_rows:
                    db.session.add(StudentFeeItem(
                        student_id=s.id, academic_year=action_year,
                        category=row.category, custom_category=row.custom_category, amount=row.amount,
                    ))
                _refresh_current_year_cache(s)
                db.session.commit()
                if structure_rows:
                    flash(f"Fee items reset to the {s.class_name} {action_year} structure.")
                else:
                    flash(f"No fee structure defined for {s.class_name} in {action_year} — items cleared.")

            elif action == "update_due_date":
                s.fee.due_date = request.form.get("due_date", "").strip()
                db.session.commit()
                flash("Due date updated.")

            elif action == "add_payment":
                amount = float(request.form.get("amount") or 0)
                if amount <= 0:
                    flash("Payment amount must be greater than zero.")
                else:
                    fee_item_id = request.form.get("fee_item_id", "").strip()
                    fee_item = None
                    if fee_item_id:
                        fee_item = StudentFeeItem.query.get(int(fee_item_id))
                        if not fee_item or fee_item.student_id != s.id or fee_item.category == CONCESSION_CATEGORY:
                            flash("Please choose a valid fee category to pay against, or leave it general.")
                            fee_item = "invalid"
                    if fee_item != "invalid":
                        payment = FeePayment(
                            student_id=s.id, fee_item_id=fee_item.id if fee_item else None,
                            amount=amount, date=request.form.get("date") or None,
                            mode=request.form.get("mode", "Cash"), note=request.form.get("note", "").strip(),
                        )
                        db.session.add(payment)
                        db.session.commit()
                        against = f" against {fee_item.custom_category or fee_item.category}" if fee_item else ""
                        flash(f"Payment of ₹{amount:,.2f}{against} recorded.")

            elif action == "edit_payment":
                payment = FeePayment.query.get_or_404(int(request.form.get("payment_id")))
                if payment.student_id != s.id:
                    flash("That payment doesn't belong to this student.")
                else:
                    amount = float(request.form.get("amount") or 0)
                    if amount <= 0:
                        flash("Payment amount must be greater than zero.")
                    else:
                        fee_item_id = request.form.get("fee_item_id", "").strip()
                        fee_item = None
                        if fee_item_id:
                            fee_item = StudentFeeItem.query.get(int(fee_item_id))
                            if not fee_item or fee_item.student_id != s.id or fee_item.category == CONCESSION_CATEGORY:
                                flash("Please choose a valid fee category to pay against, or leave it general.")
                                fee_item = "invalid"
                        if fee_item != "invalid":
                            payment.amount = amount
                            payment.fee_item_id = fee_item.id if fee_item else None
                            payment.date = request.form.get("date") or payment.date
                            payment.mode = request.form.get("mode", payment.mode)
                            payment.note = request.form.get("note", "").strip()
                            db.session.commit()
                            flash("Payment entry updated.")
        except (ValueError, SQLAlchemyError):
            db.session.rollback()
            flash("Please enter a valid amount. Nothing was saved.")
        return redirect(url_for("fees.student_fee_detail", student_id=s.id, year=action_year))

    items = StudentFeeItem.query.filter_by(student_id=s.id, academic_year=viewing_year).order_by(StudentFeeItem.id).all()
    structure_by_key = {
        (row.category, row.custom_category): row.amount
        for row in FeeStructure.query.filter_by(class_name=s.class_name, academic_year=viewing_year).all()
    }
    for item in items:
        default_amount = structure_by_key.get((item.category, item.custom_category))
        item.differs_from_default = default_amount is not None and item.amount != default_amount
        item.default_amount = default_amount
        # Category-wise paid/balance, from payments actually linked to this
        # specific item — not a category isn't "chargeable" in the concession
        # case, so this is only meaningful (and only shown) for fee lines.
        item.paid_amount = sum(p.amount for p in item.payments)
        item.balance_amount = item.amount - item.paid_amount

    years_with_items = {
        row[0] for row in db.session.query(StudentFeeItem.academic_year).filter_by(student_id=s.id).distinct().all()
    }
    years_with_items.add(viewing_year)
    year_choices = sorted(years_with_items, reverse=True)

    paid = sum(p.amount for p in s.payments)
    payments = sorted(s.payments, key=lambda p: p.id, reverse=True)
    # Payments recorded without picking a category — still counted in the
    # totals above, just not attributable to any one fee line.
    unallocated_paid = sum(p.amount for p in s.payments if p.fee_item_id is None)
    payable_items = [i for i in items if i.category != CONCESSION_CATEGORY]

    # Everything shown on THIS page (cards, Fee Items footer, status banner)
    # is computed directly from this year's own items — not from the
    # StudentFee cache, which intentionally always reflects the school's
    # current academic year for the Fee Ledger/dashboard instead (see
    # _refresh_current_year_cache). That keeps a past/future year's detail
    # page accurate even though it isn't "the" current year.
    concession_total = abs(sum(i.amount for i in items if i.category == CONCESSION_CATEGORY))
    total_fee_for_year = sum(i.amount for i in items)
    gross_total = total_fee_for_year + concession_total
    balance = total_fee_for_year - paid

    return render_template(
        "student_fee_detail.html", s=s, paid=paid, balance=balance, payments=payments,
        items=items, viewing_year=viewing_year, year_choices=year_choices, category_choices=FEE_CATEGORIES,
        concession_reasons=CONCESSION_REASONS, concession_category=CONCESSION_CATEGORY,
        concession_total=concession_total, gross_total=gross_total, total_fee_for_year=total_fee_for_year,
        unallocated_paid=unallocated_paid, payable_items=payable_items,
    )


@bp.route("/fees/payment/<int:payment_id>/delete", methods=["POST"])
@login_required
def delete_payment(payment_id):
    p = FeePayment.query.get_or_404(payment_id)
    student_id = p.student_id
    db.session.delete(p)
    db.session.commit()
    flash("Payment entry removed.")
    return redirect(url_for("fees.student_fee_detail", student_id=student_id))


@bp.route("/fees/payment/<int:payment_id>/receipt")
@login_required
def fee_receipt(payment_id):
    p = FeePayment.query.get_or_404(payment_id)
    s = p.student

    # Now that payments can be tagged to a specific fee item, the breakdown
    # is exact — each fee line's Paid/Balance/status comes straight from the
    # payments actually recorded against it, not a best-guess allocation.
    # Concession/Discount lines are shown separately below with no
    # Paid/Due status of their own, since they aren't something to pay off.
    total_paid_to_date = sum(payment.amount for payment in s.payments)
    academic_year = s.fee.academic_year if s.fee else None
    items = (
        StudentFeeItem.query.filter_by(student_id=s.id, academic_year=academic_year).order_by(StudentFeeItem.id).all()
        if academic_year else []
    )
    fee_lines = [i for i in items if i.category != CONCESSION_CATEGORY]
    concession_lines = [i for i in items if i.category == CONCESSION_CATEGORY]

    fee_breakdown = []
    for item in fee_lines:
        item_paid = sum(pay.amount for pay in item.payments)
        item_balance = item.amount - item_paid
        status = "Paid" if item_balance <= 0 else ("Partial" if item_paid > 0 else "Due")
        fee_breakdown.append({
            "label": item.custom_category if item.category == "Other" else item.category,
            "amount": item.amount, "paid_amount": item_paid, "status": status,
        })

    concession_breakdown = [
        {"label": i.custom_category, "amount": i.amount}
        for i in concession_lines
    ]

    unallocated_paid = sum(pay.amount for pay in s.payments if pay.fee_item_id is None)
    payment_category_label = (
        (p.fee_item.custom_category or p.fee_item.category) if p.fee_item_id and p.fee_item else "General"
    )

    total_fee = s.fee.total_fee if s.fee else 0
    balance_due = total_fee - total_paid_to_date

    return render_template(
        "receipt.html", kind="fee", payment=p, person=s,
        printed_on=datetime.now().strftime("%Y-%m-%d %H:%M"),
        fee_breakdown=fee_breakdown, concession_breakdown=concession_breakdown, total_fee=total_fee,
        total_paid_to_date=total_paid_to_date, balance_due=balance_due,
        unallocated_paid=unallocated_paid, payment_category_label=payment_category_label,
    )
